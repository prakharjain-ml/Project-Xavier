"""Path-planning preview: see what the planner would tell the motors, with no motors, gaze or headset.

    python -m vision.nav_preview                 # forward camera found automatically (the one without a face)
    python -m vision.nav_preview --source 0
    python -m vision.nav_preview --cam-height 0.9 --cam-pitch 20   # where the phone sits on the chair
Keys: 1-4 pick the target (default: the biggest object), Q / ESC quit. Nothing is sent to any motor.

On screen: the shortest safe path (A*) drawn on the floor as a blue ribbon as wide as the chair, a ring where the
chair will stop, a thin line for the arc the planner is driving right now, corner-bracket boxes, and a stats
panel (target, distance, path length, ETA, clearance, motor command and wheel bars).
"""

from __future__ import annotations

import argparse
import logging
import math
import sys
import time

import numpy as np

from control.astar import astar_path, path_length
from control.goto import NavState, nav_step, obstacles_from_tracks
from control.navigation import ARRIVE_M, NavConfig, goal_from_target, motion
from vision import hud
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
from vision.floor import project_floor

log = logging.getLogger("vision.nav_preview")

DEAD_ZONE = 10  # firmware speed units below this count as "stopped" (the board ignores |speed| < 50 anyway)
VIEW_W, PANEL_W = 1280, 420  # camera drawn 1280 px wide, stats panel 420 px to its right
ETA_SPEED_MPS = 0.4  # typical cruising speed used for the ETA estimate
FLOW_MPS = 0.6  # how fast the arrows on the floor path flow toward the target
CAM_HEIGHT_M, CAM_PITCH_DEG = 1.0, 15.0  # phone lens height above the floor and downward tilt (measure on the chair)
WINDOW = "Xavier path preview (1-4 target, Q quit)"


def direction_label(left: int, right: int) -> str:
    """Wheel speeds -> plain words (positive = forward)."""
    if abs(left) < DEAD_ZONE and abs(right) < DEAD_ZONE:
        return "STOP"
    if left * right < 0:  # wheels turning opposite ways: spinning in place
        return "SPIN RIGHT" if left > right else "SPIN LEFT"
    if abs(left - right) <= max(4, 0.1 * max(abs(left), abs(right))):
        return "FORWARD" if left + right > 0 else "BACKWARD"
    return "FORWARD + RIGHT" if left > right else "FORWARD + LEFT"


def stop_point(goal) -> tuple[float, float]:
    """Where the chair stops: ARRIVE_M short of the object, on the straight line to it (chair frame, metres)."""
    dist = math.hypot(*goal)
    if dist <= ARRIVE_M:
        return 0.0, 0.0
    scale = (dist - ARRIVE_M) / dist
    return goal[0] * scale, goal[1] * scale


def path_clearance(path, obstacles: np.ndarray) -> float | None:
    """Closest any point of the path comes to an obstacle point (metres); None when there are no obstacles."""
    if path is None or len(path) < 2 or len(obstacles) == 0:
        return None
    pts = np.array(path, float)
    dense = np.concatenate([np.linspace(a, b, 20) for a, b in zip(pts, pts[1:])])
    return float(np.linalg.norm(dense[:, None, :] - np.asarray(obstacles)[None, :, :], axis=2).min())


def dwa_arc(nav: NavState, cfg: NavConfig) -> np.ndarray:
    """The arc the planner is driving right now, 3 s ahead (chair frame)."""
    state, arc = np.zeros(5), []
    for _ in range(int(cfg.predict_time / cfg.dt) * 2):
        state = motion(state, (nav.v, nav.w), cfg.dt)
        arc.append(state[:2].copy())
    return np.array(arc)


def stats_sections(target, goal, path, obstacles, nav: NavState) -> list[tuple[str, str]]:
    """The (title, value) rows of the side panel."""
    clearance = path_clearance(path, obstacles)
    length = path_length(path) if path else None
    if goal is None:
        where = "-"
    else:
        bearing = math.degrees(math.atan2(goal[1], goal[0]))  # y is left, so positive = to the left
        where = f"{math.hypot(*goal):.2f} m  /  {abs(bearing):.0f} deg {'L' if bearing > 0 else 'R'}"
    if goal is not None and path is None:
        route = "NO SAFE PATH"
    else:
        route = "-" if length is None else f"{length:.2f} m  /  {length / ETA_SPEED_MPS:.0f} s"
    return [
        ("target", "-" if target is None else f"{target.label.upper()}  #{target.id}"),
        ("distance / bearing", where),
        ("path / eta", route),
        ("clearance", "-" if clearance is None else f"{clearance:.2f} m"),
        ("obstacles", str(len(obstacles) // 3)),  # obstacles_from_tracks gives 3 points per object
        ("speed / turn", f"{nav.v:.2f} m/s  /  {math.degrees(nav.w):+.0f} deg/s"),
    ]


def compose(cv2, frame, targets, target, nav: NavState, wheels, arrived: bool, hfov: float, cam_h: float,
            pitch: float, fps: float, cfg: NavConfig, phase: float = 0.0) -> np.ndarray:
    """One HUD frame: tinted camera with the floor path, ring, arc and boxes, plus the stats panel on the right."""
    h, w = frame.shape[:2]

    def project(points):
        return project_floor(points, w, h, hfov, cam_h, pitch)

    navy = np.full_like(frame, hud.bgr(hud.PALETTE["navy"]))
    view = cv2.addWeighted(frame, 0.78, navy, 0.22, 0)  # slight blue grade so the HUD colours sit on the image
    goal = path = None
    obstacles = np.zeros((0, 2))
    if target is not None and target.distance_m:
        offset = ((target.bbox[0] + target.bbox[2]) / 2 - w / 2) / (w / 2)
        goal = goal_from_target(offset, target.distance_m, hfov)
        obstacles = obstacles_from_tracks(targets, target.id, w, hfov)
        stop = stop_point(goal)
        path = astar_path(stop, obstacles)  # shortest route that keeps the chair clear of every obstacle
        view = hud.draw_floor_path(view, path, project, phase=phase)
        view = hud.draw_ground_ring(view, stop, project)
        arc = project(dwa_arc(nav, cfg))
        arc = arc[~np.isnan(arc).any(axis=1)].astype(np.int32)
        if len(arc) > 1:
            cv2.polylines(view, [arc], False, hud.bgr(hud.PALETTE["sky"]), 2, cv2.LINE_AA)
    text = hud.TextLayer()
    for slot, t in enumerate(targets):
        chosen = target is not None and t.id == target.id
        color = hud.PALETTE["ice"] if chosen else hud.PALETTE["sky"]
        view = hud.corner_box(view, t.bbox, color, 4 if chosen else 2, glow=chosen)
        dist = "" if t.distance_m is None else f"  {t.distance_m:.1f} m"
        text.add(f"{slot + 1}  {t.label.upper()}{dist}", (int(t.bbox[0]) + 6, max(30, int(t.bbox[1]) - 8)),
                 26 if chosen else 20, color, "num", "ld")
    text.add("XAVIER  //  PATH PREVIEW  //  NO MOTOR OUTPUT", (24, 22), 18)
    view = text.render(view)
    label = "NO TARGET" if target is None else ("ARRIVED" if arrived else direction_label(*wheels))
    panel = hud.side_panel(h, PANEL_W, {
        "sections": stats_sections(target, goal, path, obstacles, nav), "command": label,
        "left": wheels[0], "right": wheels[1],
        "footer": f"{fps:.0f} FPS   FOV {hfov:.1f} deg   CAM {cam_h:.2f} m / {pitch:.0f} deg down"})
    return np.hstack([view, panel])


def run(cv2, reader, model, classes, hfov: float, seconds: float | None, cam_h: float, pitch: float) -> None:
    cfg, nav, choice, first_seen, last_t, last_log = NavConfig(), NavState(), None, {}, None, 0.0
    fps, prev = 0.0, time.monotonic()
    start = prev
    while seconds is None or time.monotonic() - start < seconds:
        key = cv2.waitKey(1) & 0xFF
        if key in (27, ord("q")):
            break
        snapshot = reader.latest()
        if snapshot is None or snapshot[1] == last_t:
            continue
        raw, last_t = snapshot
        frame = cv2.resize(raw, (VIEW_W, int(raw.shape[0] * VIEW_W / raw.shape[1])))  # same view, fewer pixels
        w = frame.shape[1]
        now = time.monotonic()
        fps = 0.9 * fps + 0.1 / max(1e-3, now - prev)  # smoothed frame rate
        prev = now
        tracks = detect(model, frame, focal_length_px(w, hfov), "mps", classes)
        first_seen = {**{t.id: now for t in tracks if t.id not in first_seen}, **first_seen}
        targets = separate_targets(pick_targets(tracks, first_seen, max_n=len(tracks)), w, MAX_TARGETS)
        if ord("1") <= key <= ord("4") and key - ord("1") < len(targets):
            choice = targets[key - ord("1")].id
        target = next((t for t in targets if t.id == choice), None)
        if target is None and targets:  # default: the biggest object in view
            target = max(targets, key=lambda t: (t.bbox[2] - t.bbox[0]) * (t.bbox[3] - t.bbox[1]))
        wheels, arrived = (0, 0), False
        if target is not None:
            nav, wheels, arrived = nav_step(nav, target, targets, w, hfov, distance_cm=None, cfg=cfg)
        else:
            nav = NavState()
        cv2.imshow(WINDOW, compose(cv2, frame, targets, target, nav, wheels, arrived, hfov, cam_h, pitch, fps, cfg,
                                   phase=now * FLOW_MPS))
        if now - last_log >= 1.0:
            last_log = now
            label = "NO TARGET" if target is None else ("ARRIVED" if arrived else direction_label(*wheels))
            what = "none" if target is None else f"{target.label} {target.distance_m or 0:.1f} m"
            log.info("target=%s -> %s (left %+d, right %+d)", what, label, *wheels)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    parser = argparse.ArgumentParser(description="Show what the path planner would tell the motors.")
    parser.add_argument("--source", default="auto", help="camera index, or auto = the camera without a face")
    parser.add_argument("--seconds", type=float, default=None)
    parser.add_argument("--cam-height", type=float, default=CAM_HEIGHT_M, help="camera height above floor (m)")
    parser.add_argument("--cam-pitch", type=float, default=CAM_PITCH_DEG, help="camera tilt down (degrees)")
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
        run(cv2, reader, model, relevant_class_ids(model.names), load_hfov(), args.seconds,
            args.cam_height, args.cam_pitch)
    finally:
        reader.stop()
        cv2.destroyAllWindows()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
