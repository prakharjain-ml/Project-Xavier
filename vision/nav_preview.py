"""Path-planning preview: see what the planner would tell the motors, with no motors, gaze or headset.

    python -m vision.nav_preview                 # forward camera found automatically (the one without a face)
    python -m vision.nav_preview --source 0
Keys: 1-4 pick the target (default: the biggest object), Q / ESC quit. Nothing is sent to any motor.

On screen: boxes (target green, obstacles red), the motor command in words with left/right wheel speeds, and a
top-down map (chair at the bottom, metres) with the arc the planner is about to drive.
"""

from __future__ import annotations

import argparse
import logging
import math
import sys
import time

import numpy as np

from control.goto import NavState, nav_step, obstacles_from_tracks
from control.navigation import NavConfig, goal_from_target, motion
from vision.detect_track import (
    DEFAULT_MODEL,
    MAX_TARGETS,
    detect,
    focal_length_px,
    load_hfov,
    pick_targets,
    relevant_class_ids,
    separate_targets,
)

log = logging.getLogger("vision.nav_preview")

DEAD_ZONE = 10  # firmware speed units below this count as "stopped" (the board ignores |speed| < 50 anyway)
MAP_PX, MAP_M = 320, 4.0  # top-down map: 320 px square showing 4 m ahead
GREEN, RED, WHITE, YELLOW = (0, 220, 0), (0, 0, 255), (255, 255, 255), (0, 220, 255)


def direction_label(left: int, right: int) -> str:
    """Wheel speeds -> plain words (positive = forward)."""
    if abs(left) < DEAD_ZONE and abs(right) < DEAD_ZONE:
        return "STOP"
    if left * right < 0:  # wheels turning opposite ways: spinning in place
        return "SPIN RIGHT" if left > right else "SPIN LEFT"
    if abs(left - right) <= max(4, 0.1 * max(abs(left), abs(right))):
        return "FORWARD" if left + right > 0 else "BACKWARD"
    return "FORWARD + RIGHT" if left > right else "FORWARD + LEFT"


def to_map(point, origin=(MAP_PX // 2, MAP_PX - 10)) -> tuple[int, int]:
    """Chair frame (x forward, y left, metres) -> map pixels (chair at bottom centre, forward = up)."""
    scale = (MAP_PX - 20) / MAP_M
    return int(origin[0] - point[1] * scale), int(origin[1] - point[0] * scale)


def draw_map(cv2, canvas, goal, obstacles, nav: NavState, cfg: NavConfig) -> None:
    panel = np.full((MAP_PX, MAP_PX, 3), 30, np.uint8)
    for metres in (1, 2, 3, 4):  # range rings
        cv2.circle(panel, to_map((0, 0)), int((MAP_PX - 20) / MAP_M * metres), (70, 70, 70), 1)
    for p in obstacles:
        cv2.circle(panel, to_map(p), 6, RED, -1)
    if goal is not None:
        cv2.circle(panel, to_map(goal), 9, GREEN, -1)
    state, arc = np.zeros(5), []
    for _ in range(int(cfg.predict_time / cfg.dt) * 2):  # the arc the planner chose, drawn 3 s ahead
        state = motion(state, (nav.v, nav.w), cfg.dt)
        arc.append(to_map(state[:2]))
    for a, b in zip(arc, arc[1:]):
        cv2.line(panel, a, b, YELLOW, 2)
    cv2.rectangle(panel, (MAP_PX // 2 - 12, MAP_PX - 22), (MAP_PX // 2 + 12, MAP_PX - 2), WHITE, -1)  # the chair
    canvas[10:10 + MAP_PX, canvas.shape[1] - MAP_PX - 10:canvas.shape[1] - 10] = panel


def run(cv2, reader, model, classes, hfov: float, seconds: float | None) -> None:
    cfg, nav, choice, first_seen, last_t, last_log = NavConfig(), NavState(), None, {}, None, 0.0
    start = time.monotonic()
    while seconds is None or time.monotonic() - start < seconds:
        key = cv2.waitKey(1) & 0xFF
        if key in (27, ord("q")):
            break
        snapshot = reader.latest()
        if snapshot is None or snapshot[1] == last_t:
            continue
        frame, last_t = snapshot
        h, w = frame.shape[:2]
        now = time.monotonic()
        tracks = detect(model, frame, focal_length_px(w, hfov), "mps", classes)
        first_seen = {**{t.id: now for t in tracks if t.id not in first_seen}, **first_seen}
        targets = separate_targets(pick_targets(tracks, first_seen, max_n=len(tracks)), w, MAX_TARGETS)
        if ord("1") <= key <= ord("4") and key - ord("1") < len(targets):
            choice = targets[key - ord("1")].id
        target = next((t for t in targets if t.id == choice), None)
        if target is None and targets:  # default: the biggest object in view
            target = max(targets, key=lambda t: (t.bbox[2] - t.bbox[0]) * (t.bbox[3] - t.bbox[1]))
        goal, wheels, arrived = None, (0, 0), False
        obstacles = np.zeros((0, 2))
        if target is not None:
            nav, wheels, arrived = nav_step(nav, target, targets, w, hfov, distance_cm=None, cfg=cfg)
            offset = ((target.bbox[0] + target.bbox[2]) / 2 - w / 2) / (w / 2)
            goal = goal_from_target(offset, target.distance_m, hfov) if target.distance_m else None
            obstacles = obstacles_from_tracks(targets, target.id, w, hfov)
        else:
            nav = NavState()
        label = "NO TARGET" if target is None else ("ARRIVED" if arrived else direction_label(*wheels))
        canvas = frame.copy()
        for slot, t in enumerate(targets):
            color = GREEN if target is not None and t.id == target.id else RED
            x1, y1, x2, y2 = map(int, t.bbox)
            cv2.rectangle(canvas, (x1, y1), (x2, y2), color, 6 if color == GREEN else 3)
            dist = "?" if t.distance_m is None else f"{t.distance_m:.1f} m"
            cv2.putText(canvas, f"[{slot + 1}] {t.label} {dist}", (x1 + 8, max(40, y1 + 44)),
                        cv2.FONT_HERSHEY_SIMPLEX, 1.3, color, 3)
        cv2.putText(canvas, f"MOTORS: {label}", (30, h - 90), cv2.FONT_HERSHEY_SIMPLEX, 2.4, YELLOW, 6)
        cv2.putText(canvas, f"left wheel {wheels[0]:+d}   right wheel {wheels[1]:+d}   (nothing is sent)",
                    (30, h - 30), cv2.FONT_HERSHEY_SIMPLEX, 1.3, WHITE, 3)
        draw_map(cv2, canvas, goal, obstacles, nav, cfg)
        cv2.imshow("path planning preview (1-4 target, Q quit)", canvas)
        if now - last_log >= 1.0:
            last_log = now
            what = "none" if target is None else f"{target.label} {target.distance_m:.1f} m" if target.distance_m else target.label
            log.info("target=%s obstacles=%d -> %s (left %+d, right %+d)", what, len(obstacles) // 3, label, *wheels)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    parser = argparse.ArgumentParser(description="Show what the path planner would tell the motors.")
    parser.add_argument("--source", default="auto", help="camera index, or auto = the camera without a face")
    parser.add_argument("--seconds", type=float, default=None)
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    import cv2
    from ultralytics import YOLO

    from vision.camera_source import LatestFrameReader, open_capture, parse_source

    source = args.source
    if source == "auto":
        from vision.camera_roles import probe_cameras

        rooms = [p.index for p in probe_cameras() if not p.sees_face]
        if not rooms:
            log.error("no forward camera found (every camera sees a face, or none is connected)")
            return 2
        source = str(rooms[0])
    log.info("forward camera %s, field of view %.1f deg", source, load_hfov())
    reader = LatestFrameReader(parse_source(source), opener=open_capture)
    reader.start()
    model = YOLO(DEFAULT_MODEL)
    try:
        run(cv2, reader, model, relevant_class_ids(model.names), load_hfov(), args.seconds)
    finally:
        reader.stop()
        cv2.destroyAllWindows()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
