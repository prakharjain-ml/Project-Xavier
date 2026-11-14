"""Choose a real object by looking at it (gaze fallback, Mode 2 step 1). OpenCV window only, no pygame.

The forward camera (Pixel / Logitech) shows the room full-screen with a red box on up to 4 objects (YOLO +
ByteTrack from vision/detect_track.py). The eye tracker (built-in camera, its own program) moves a green
cursor. The box under the cursor turns YELLOW and a bar fills; holding your gaze for DWELL_S confirms it
(GREEN). Later the confirmation also needs the EEG (the yellow box flickers, SSVEP must agree).
Confirming only reports the choice: nothing drives the chair from here yet.

    python -m vision.object_select --source 1 --eye-camera 0
Keys: C = re-centre (look at the + first), X = cancel confirmation, Q / ESC = quit.
The window is full-screen, like the calibration screen, so gaze (0-1 screen coordinates) lines up with it.
"""

from __future__ import annotations

import argparse
import logging
import os
import queue
import subprocess
import sys
import time
from dataclasses import dataclass, replace

import numpy as np

from shared.protocol import DWELL_S, STALE_INTENT_S
from vision.detect_track import (
    DEFAULT_MODEL,
    MAX_TARGETS,
    Track,
    detect,
    focal_length_px,
    pick_targets,
    relevant_class_ids,
    separate_targets,
    steering_offset,
)
from vision.destinations import iou
from vision.gaze import GazeSample, pick_region

log = logging.getLogger("vision.object_select")

WINDOW = "look at an object to choose it"
CANVAS_W, CANVAS_H = 1280, 800  # same canvas as the calibration screen, stretched to full screen
MIN_HIT_SIZE = 0.12  # small objects get a gaze target at least 12% of the screen wide and tall
SAME_OBJECT_IOU = 0.3  # a relabelled box overlapping the previous candidate this much is the same object
RED, YELLOW, GREEN, GREY, CURSOR = (0, 0, 255), (0, 220, 255), (0, 220, 0), (160, 160, 160), (255, 120, 0)


@dataclass(frozen=True)
class Selection:
    candidate: int | None = None  # object under the gaze right now
    since: float | None = None  # when the gaze landed on it
    confirmed: int | None = None  # last confirmed object (stays until another is confirmed or X cancels)
    box: tuple[float, float, float, float] | None = None  # candidate's last gaze box (0-1 screen coordinates)


def update_selection(sel: Selection, hit: int | None, now: float, dwell_s: float = DWELL_S,
                     box: tuple[float, float, float, float] | None = None) -> Selection:
    """Dwell confirmation: same object under the gaze for dwell_s -> confirmed. Looking away restarts the dwell.

    If the tracker relabels the object under the gaze (new ID, box in the same place: overlap >= SAME_OBJECT_IOU),
    it is the same object, so the dwell keeps running instead of restarting.
    """
    if hit is None:
        return replace(sel, candidate=None, since=None, box=None)
    if hit != sel.candidate:
        same_object = box is not None and sel.box is not None and iou(box, sel.box) >= SAME_OBJECT_IOU
        if same_object:
            confirmed = hit if sel.confirmed == sel.candidate else sel.confirmed
            return replace(sel, candidate=hit, box=box, confirmed=confirmed)
        return replace(sel, candidate=hit, since=now, box=box)
    sel = replace(sel, box=box if box is not None else sel.box)
    if now - sel.since >= dwell_s:
        return replace(sel, confirmed=hit)
    return sel


def gaze_problem(sample: GazeSample | None, now: float) -> str | None:
    """Why there is no usable gaze right now (for the summary), or None if gaze is fine."""
    if sample is None:
        return "no_sample"
    if now - sample.t > STALE_INTENT_S:
        return "stale"
    if sample.point is not None:
        return None
    return "eyes_closed" if sample.closed else "no_face"


def dwell_fraction(sel: Selection, now: float, dwell_s: float = DWELL_S) -> float:
    return 0.0 if sel.since is None else min(1.0, (now - sel.since) / dwell_s)


def hit_boxes(targets: list[Track], frame_w: int, frame_h: int,
              min_size: float = MIN_HIT_SIZE) -> dict[int, tuple[float, float, float, float]]:
    """Each target's gaze area in 0-1 screen coordinates. Small objects are enlarged around their centre to at
    least min_size (webcam gaze is only accurate to a few degrees), shifted to stay on screen."""
    boxes = {}
    for t in targets:
        x1, y1, x2, y2 = t.bbox[0] / frame_w, t.bbox[1] / frame_h, t.bbox[2] / frame_w, t.bbox[3] / frame_h
        w, h = max(x2 - x1, min_size), max(y2 - y1, min_size)
        cx = min(max((x1 + x2) / 2, w / 2), 1 - w / 2)
        cy = min(max((y1 + y2) / 2, h / 2), 1 - h / 2)
        boxes[t.id] = (cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)
    return boxes


def corrected_point(sample: GazeSample | None, offset: tuple[float, float], now: float) -> tuple[float, float] | None:
    """Fresh gaze point plus the re-centring offset, or None if there is no usable fresh gaze."""
    if sample is None or sample.point is None or now - sample.t > STALE_INTENT_S:
        return None
    return (min(1.0, max(0.0, sample.point[0] + offset[0])), min(1.0, max(0.0, sample.point[1] + offset[1])))


def newest(q: queue.Queue, current):
    while True:
        try:
            current = q.get_nowait()
        except queue.Empty:
            return current


def draw(cv2, frame: np.ndarray, targets: list[Track], boxes: dict, sel: Selection, point, now: float,
         status: str) -> np.ndarray:
    canvas = cv2.resize(frame, (CANVAS_W, CANVAS_H))
    for t in targets:
        x1, y1, x2, y2 = (int(v * s) for v, s in zip(boxes[t.id], (CANVAS_W, CANVAS_H, CANVAS_W, CANVAS_H)))
        color = GREEN if t.id == sel.confirmed else YELLOW if t.id == sel.candidate else RED
        cv2.rectangle(canvas, (x1, y1), (x2, y2), color, 6 if color != RED else 3)
        dist = "" if t.distance_m is None else f" ~{t.distance_m:.1f} m"
        cv2.putText(canvas, f"{t.label}{dist}", (x1 + 6, max(24, y1 + 28)), cv2.FONT_HERSHEY_SIMPLEX, 0.8, color, 2)
        if t.id == sel.candidate and t.id != sel.confirmed:  # dwell progress bar
            cv2.rectangle(canvas, (x1, y2 + 6), (x1 + int((x2 - x1) * dwell_fraction(sel, now)), y2 + 18), YELLOW, -1)
    cx, cy = CANVAS_W // 2, CANVAS_H // 2
    cv2.line(canvas, (cx - 15, cy), (cx + 15, cy), GREY, 2)
    cv2.line(canvas, (cx, cy - 15), (cx, cy + 15), GREY, 2)
    if point is not None:
        cv2.circle(canvas, (int(point[0] * CANVAS_W), int(point[1] * CANVAS_H)), 14, CURSOR, -1)
    cv2.putText(canvas, status, (12, CANVAS_H - 16), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
    return canvas


def run(cv2, reader, model, classes, gaze_queue, hfov: float, device: str, seconds: float | None,
        tracker_alive=lambda: True) -> list[str]:
    sel, offset, sample, hit = Selection(), (0.0, 0.0), None, None
    first_seen: dict[int, float] = {}
    targets: list[Track] = []
    frame, last_t, confirmations = None, None, []
    gaze_frames = total_frames = 0
    problems: dict[str | None, int] = {}
    start = time.monotonic()
    while seconds is None or time.monotonic() - start < seconds:
        key = cv2.waitKey(1) & 0xFF
        if key in (27, ord("q")):
            break
        if not tracker_alive():  # a live test once ran 4 minutes with a dead tracker: stop and say so
            log.error("eye tracker stopped (see its error above): no gaze possible, ending the session")
            break
        now = time.monotonic()
        snapshot = reader.latest()
        if snapshot is not None and snapshot[1] != last_t:  # new camera frame: run YOLO + tracking once
            frame, last_t = snapshot
            tracks = detect(model, frame, focal_length_px(frame.shape[1], hfov), device, classes)
            first_seen = {**{t.id: now for t in tracks if t.id not in first_seen}, **first_seen}
            targets = separate_targets(pick_targets(tracks, first_seen, max_n=len(tracks)), frame.shape[1], MAX_TARGETS)
        if frame is None:
            continue
        sample = newest(gaze_queue, sample)
        if key == ord("c") and sample is not None and sample.point is not None:
            offset = (0.5 - sample.point[0], 0.5 - sample.point[1])  # rider is looking at the "+"
            log.info("re-centred: offset %.3f, %.3f", *offset)
        if key == ord("x"):
            sel = replace(sel, confirmed=None)
        point = corrected_point(sample, offset, now)
        boxes = hit_boxes(targets, frame.shape[1], frame.shape[0])
        hit = pick_region(point, boxes, hit) if point is not None else None
        before = sel.confirmed
        sel = update_selection(sel, hit, now, box=boxes.get(hit) if hit is not None else None)
        problem = gaze_problem(sample, now)
        problems[problem] = problems.get(problem, 0) + 1
        if sel.confirmed is not None and sel.confirmed != before:
            chosen = next(t for t in targets if t.id == sel.confirmed)
            dist = "?" if chosen.distance_m is None else f"~{chosen.distance_m:.1f} m"
            line = f"CONFIRMED {chosen.label} #{chosen.id} {dist} steer {steering_offset(chosen.bbox, frame.shape[1]):+.2f}"
            log.info(line)
            confirmations.append(line)
        total_frames += 1
        gaze_frames += point is not None
        status = ("NO GAZE (face not seen / eyes closed)" if point is None else
                  "look at an object for 1.5 s to confirm  |  C re-centre  X cancel  Q quit")
        cv2.imshow(WINDOW, draw(cv2, frame, targets, boxes, sel, point, now, status))
    log.info("gaze available in %.0f%% of frames", 100 * gaze_frames / max(total_frames, 1))
    lost = ", ".join(f"{name}={100 * n / max(total_frames, 1):.0f}%" for name, n in problems.items() if name)
    log.info("gaze lost because: %s", lost or "never lost")
    return confirmations


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="Choose a real object by looking at it.")
    parser.add_argument("--source", default="auto", help="forward camera index/URL, or auto (= not the face camera)")
    parser.add_argument("--eye-camera", default="auto", help="camera that sees the rider's face, or auto")
    parser.add_argument("--calibration", default="data/raw/gaze_calibration.json")
    parser.add_argument("--hfov", type=float, default=70.0)
    parser.add_argument("--device", default="mps")
    parser.add_argument("--seconds", type=float, default=None)
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    if not os.path.exists(args.calibration):
        log.error("no gaze calibration at %s: run `python -m vision.gaze_calibrate` first", args.calibration)
        return 2
    import cv2
    from ultralytics import YOLO

    from vision.camera_source import LatestFrameReader, open_capture, parse_source
    from vision.gaze_link import start_gaze_tracker

    if "auto" in (args.source, args.eye_camera):
        from vision.camera_roles import assign_roles, probe_cameras

        probes = probe_cameras()
        log.info("cameras: %s", ", ".join(f"{p.index}{' (face)' if p.sees_face else ''}" for p in probes))
        try:
            eye, forward = assign_roles(probes)
        except RuntimeError as error:
            log.error("%s", error)
            return 2
        args.eye_camera = eye if args.eye_camera == "auto" else int(args.eye_camera)
        args.source = str(forward) if args.source == "auto" else args.source
        log.info("eye camera = %s, forward camera = %s", args.eye_camera, args.source)
    reader = LatestFrameReader(parse_source(args.source), opener=open_capture)
    reader.start()
    process, gaze_queue, gaze_stop = start_gaze_tracker(int(args.eye_camera), args.calibration)
    model = YOLO(DEFAULT_MODEL)
    cv2.namedWindow(WINDOW, cv2.WINDOW_NORMAL)
    cv2.setWindowProperty(WINDOW, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)
    try:
        confirmations = run(cv2, reader, model, relevant_class_ids(model.names), gaze_queue, args.hfov, args.device,
                            args.seconds, tracker_alive=lambda: process.poll() is None)
    finally:
        gaze_stop.set()
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
        reader.stop()
        cv2.destroyAllWindows()
    print(f"summary: confirmations={len(confirmations)}")
    for line in confirmations:
        print("  " + line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
