"""Mode 2 step 1: find objects in the camera feed, give each a steady ID, a flicker frequency and a distance.

Pipeline per frame: newest camera frame -> YOLO (what and where) -> ByteTrack (same object keeps the same ID
across frames) -> keep the 4 steadiest objects -> each gets one of the 4 SSVEP frequencies and an estimated
distance. Keys 1-4 select a target for now; later the EEG decoder makes that choice (whichever frequency wins).

Distance without LiDAR: an object of known typical height looks smaller the farther away it is.
Pinhole camera rule: distance = real_height * focal_length_px / box_height_px. It is an ESTIMATE (people and
chairs vary in size, and boxes cut off by the frame edge read too far). Calibrate --hfov with a tape measure.
This is never a safety signal: the ESP32 ultrasonic owns obstacle stops.

Run from the repo root:  python -m vision.detect_track --source 1     (q or ESC quits, 1-4 select, 0 clears)
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import os
import sys
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from shared.protocol import TARGET_FREQS_HZ as PROTOCOL_FREQS_HZ
from vision.camera_source import LatestFrameReader, open_capture, parse_source, redact_url

log = logging.getLogger("vision.detect_track")

# The 4 flicker frequencies come from the shared contract, in slot order (6.67, 8.57, 12, 15 Hz).
TARGET_FREQS_HZ = tuple(PROTOCOL_FREQS_HZ.values())
MAX_TARGETS = 4
DEFAULT_MODEL = os.path.expanduser(os.environ.get("YOLO_MODEL", "~/hp26-models/yolo11n.pt"))
DEFAULT_HFOV_DEG = 70.0  # horizontal field of view guess for a phone/webcam; calibrate with --hfov
CAMERA_CALIBRATION_PATH = "data/raw/camera_calibration.json"  # gitignored; written by the distance calibration
MIN_CONF = 0.4  # only SHOW objects YOLO is at least this sure about
TRACK_CONF = 0.1  # but give the tracker everything above this: weak detections keep an object's ID alive
TRACKER_CONFIG = str(Path(__file__).with_name("bytetrack_chair.yaml"))
# Minimum empty space between two flickering boxes, as a fraction of frame width. On the 13.6" laptop screen at
# ~55 cm viewing distance, 5% of the width is ~1.5 cm, about 1.5 degrees of visual angle: enough that staring at
# one box keeps the neighbour mostly outside the sharp centre of vision. Tune in calibration.
MIN_GAP_FRAC = 0.05
LOG_EVERY_S = 1.0
QUIT_KEYS = {ord("q"), 27}
SLOT_COLORS = ((255, 140, 0), (0, 200, 255), (200, 0, 255), (0, 220, 0))  # BGR, one per frequency slot

# Typical real heights in meters for COCO classes we may drive toward. COCO has no "door" class.
TYPICAL_HEIGHT_M = {
    "person": 1.7, "chair": 0.9, "couch": 0.85, "bench": 0.8, "dining table": 0.75, "bed": 0.6,
    "tv": 0.6, "refrigerator": 1.7, "potted plant": 0.5, "backpack": 0.5, "suitcase": 0.6,
    "laptop": 0.25, "bottle": 0.25, "cup": 0.1, "toilet": 0.75, "sink": 0.9,
    "dog": 0.5, "cat": 0.3, "bicycle": 1.0,
}

# Things a wheelchair drives to or meets on the floor indoors. Everything else (phones, cups, laptops...) is
# ignored. COCO cannot see doors, stairs or walls; that needs an open-vocabulary model (see README).
RELEVANT_CLASSES = frozenset({
    "person", "chair", "couch", "bench", "dining table", "bed", "toilet", "sink", "refrigerator", "tv",
    "potted plant", "suitcase", "backpack", "bicycle", "dog", "cat",
})


def relevant_class_ids(names: dict[int, str], relevant: frozenset[str] = RELEVANT_CLASSES) -> list[int]:
    """YOLO filters by class number, so turn our list of names into the model's numbers."""
    return sorted(i for i, name in names.items() if name in relevant)


@dataclass(frozen=True)
class Track:
    id: int
    label: str
    conf: float
    bbox: tuple[float, float, float, float]  # x1, y1, x2, y2 in pixels
    distance_m: float | None


def load_hfov(path: str | Path = CAMERA_CALIBRATION_PATH) -> float:
    """Calibrated horizontal field of view, else the default guess. Pixel, measured Sat Nov 14: 85.5 deg (the 70 deg
    guess made every distance ~40% too far)."""
    try:
        return float(json.loads(Path(path).read_text())["hfov_deg"])
    except (OSError, ValueError, KeyError, TypeError):
        return DEFAULT_HFOV_DEG


def focal_length_px(frame_width: int, hfov_deg: float) -> float:
    # Half the image width spans half the field of view: tan(hfov/2) = (width/2) / f.
    return (frame_width / 2) / math.tan(math.radians(hfov_deg) / 2)


def estimate_distance_m(label: str, box_height_px: float, focal_px: float) -> float | None:
    real_height = TYPICAL_HEIGHT_M.get(label)
    if real_height is None or box_height_px <= 0:
        return None
    return real_height * focal_px / box_height_px


def pick_targets(tracks: Sequence[Track], first_seen: dict[int, float], max_n: int = MAX_TARGETS) -> list[Track]:
    """Steadiest first (seen longest), ties broken by size, so targets do not jump around."""
    def area(t: Track) -> float:
        return (t.bbox[2] - t.bbox[0]) * (t.bbox[3] - t.bbox[1])
    return sorted(tracks, key=lambda t: (first_seen.get(t.id, math.inf), -area(t)))[:max_n]


def box_center(bbox: tuple[float, float, float, float]) -> tuple[float, float]:
    return ((bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2)


def boxes_conflict(a: Sequence[float], b: Sequence[float], min_gap_px: float) -> bool:
    """True if two boxes overlap or sit closer than min_gap_px.

    Why: the eye takes in a few degrees around the gaze point. Two flickers that close both reach the visual
    cortex, the EEG shows both frequencies, and the decoder cannot tell which one the rider means.
    The gap is the empty space between the boxes along x or y (negative when they overlap).
    """
    gap_x = max(a[0] - b[2], b[0] - a[2])
    gap_y = max(a[1] - b[3], b[1] - a[3])
    return max(gap_x, gap_y) < min_gap_px


def separate_targets(ranked: Sequence[Track], frame_width: int, max_n: int = MAX_TARGETS) -> list[Track]:
    """Walk the ranked list best-first and keep a target only if it is clear of every target already kept.

    A conflicting target is skipped (not merged), so its slot goes to the next-best target that has room.
    """
    min_gap_px = MIN_GAP_FRAC * frame_width
    kept: list[Track] = []
    for target in ranked:
        if all(not boxes_conflict(target.bbox, other.bbox, min_gap_px) for other in kept):
            kept.append(target)
        if len(kept) == max_n:
            break
    return kept


def assign_frequencies(target_ids: Sequence[int], previous: dict[int, float],
                       centers: dict[int, tuple[float, float]] | None = None) -> dict[int, float]:
    """Return a new id->frequency map (inputs untouched).

    1. Stability first: an object keeps its frequency while it stays a target (changing it would reset the
       rider's dwell and confuse them).
    2. A new object gets the free frequency that differs most from its NEAREST neighbour's frequency, so
       boxes side by side flicker as differently as possible (6.67 next to 15 Hz, not next to 8.57 Hz).
       Without centers it simply takes the first free frequency.
    """
    assigned = {tid: previous[tid] for tid in target_ids if tid in previous}
    for tid in (t for t in target_ids if t not in assigned):
        free = [f for f in TARGET_FREQS_HZ if f not in assigned.values()]
        if not free:
            break
        assigned = {**assigned, tid: max(free, key=lambda f: _margin_from_nearest(f, tid, assigned, centers))}
    return assigned


def _margin_from_nearest(freq: float, tid: int, assigned: dict[int, float],
                         centers: dict[int, tuple[float, float]] | None) -> float:
    """|freq - nearest neighbour's freq|. 0 when there is no position info or no neighbour yet."""
    if not centers or tid not in centers or not assigned:
        return 0.0
    here = centers[tid]
    neighbors = [other for other in assigned if other in centers]
    if not neighbors:
        return 0.0
    nearest = min(neighbors, key=lambda o: math.dist(here, centers[o]))
    return abs(freq - assigned[nearest])


def steering_offset(bbox: tuple[float, float, float, float], frame_width: int) -> float:
    """-1 = far left, 0 = straight ahead, +1 = far right. The future go-to-target steers to make this 0."""
    center_x = (bbox[0] + bbox[2]) / 2
    return (center_x - frame_width / 2) / (frame_width / 2)


def detect(model, frame: np.ndarray, focal_px: float, device: str, classes: list[int] | None) -> list[Track]:
    # Filtering at MIN_CONF *before* tracking starved ByteTrack's second stage (low-score matches), so an
    # object whose score dipped for a frame got a new ID. Track at TRACK_CONF, then show only >= MIN_CONF.
    result = model.track(frame, persist=True, tracker=TRACKER_CONFIG, device=device, conf=TRACK_CONF,
                         classes=classes, verbose=False)[0]
    if result.boxes is None or result.boxes.id is None:  # no confirmed tracks this frame
        return []
    tracks = []
    for tid, cls, conf, box in zip(result.boxes.id.tolist(), result.boxes.cls.tolist(),
                                   result.boxes.conf.tolist(), result.boxes.xyxy.tolist()):
        if conf < MIN_CONF:
            continue  # tracked (keeps its ID) but not shown or offered as a target
        label = result.names[int(cls)]
        tracks.append(Track(int(tid), label, conf, tuple(box), estimate_distance_m(label, box[3] - box[1], focal_px)))
    return tracks


def draw(frame: np.ndarray, targets: list[Track], freqs: dict[int, float], selected: int | None) -> np.ndarray:
    out = frame.copy()
    for slot, t in enumerate(targets):
        x1, y1, x2, y2 = map(int, t.bbox)
        color = SLOT_COLORS[TARGET_FREQS_HZ.index(freqs[t.id])]
        dist = "?" if t.distance_m is None else f"~{t.distance_m:.1f} m"
        text = f"[{slot + 1}] {t.label} #{t.id} {dist} {freqs[t.id]:.2f} Hz"
        cv2.rectangle(out, (x1, y1), (x2, y2), color, 6 if t.id == selected else 2)
        cv2.putText(out, text, (x1, max(20, y1 - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)
    return out


def selection_text(targets: list[Track], selected: int | None, frame_width: int) -> str:
    chosen = next((t for t in targets if t.id == selected), None)
    if chosen is None:
        return "press 1-4 to select a target" if selected is None else "SELECTED TARGET LOST -> would STOP"
    dist = "?" if chosen.distance_m is None else f"~{chosen.distance_m:.1f} m"
    return f"SELECTED {chosen.label} #{chosen.id}  {dist}  steer {steering_offset(chosen.bbox, frame_width):+.2f}"


def run(reader: LatestFrameReader, model, hfov_deg: float, device: str, seconds: float | None,
        classes: list[int] | None = None, ranker=None) -> str:
    first_seen: dict[int, float] = {}
    freqs: dict[int, float] = {}
    selected: int | None = None
    processed, start, last_log, last_t = 0, time.monotonic(), time.monotonic(), None
    targets: list[Track] = []
    while seconds is None or time.monotonic() - start < seconds:
        snapshot = reader.latest()
        key = cv2.waitKey(1) & 0xFF
        if key in QUIT_KEYS:
            break
        if snapshot is None or snapshot[1] == last_t:  # no new frame yet; do not re-run YOLO on the same one
            continue
        frame, last_t = snapshot
        tracks = detect(model, frame, focal_length_px(frame.shape[1], hfov_deg), device, classes)
        now = time.monotonic()
        first_seen = {**{t.id: now for t in tracks if t.id not in first_seen}, **first_seen}
        # Rank every candidate (not just 4), so a box skipped for overlapping can be replaced by the next best.
        if ranker is None:
            ranked = pick_targets(tracks, first_seen, max_n=len(tracks))
        else:  # Gemini suggestions first, then steadiest YOLO objects (see vision/destinations.py)
            from vision.destinations import rank_targets
            ranked = rank_targets(tracks, ranker.latest(), first_seen, max_n=len(tracks) + MAX_TARGETS)
        targets = separate_targets(ranked, frame.shape[1])
        freqs = assign_frequencies([t.id for t in targets], freqs, {t.id: box_center(t.bbox) for t in targets})
        if ord("1") <= key <= ord("4") and key - ord("1") < len(targets):
            selected = targets[key - ord("1")].id
        elif key == ord("0"):
            selected = None
        shown = draw(frame, targets, freqs, selected)
        cv2.putText(shown, selection_text(targets, selected, frame.shape[1]), (12, frame.shape[0] - 20),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)
        cv2.imshow("detect + track (1-4 select, 0 clear, q quit)", shown)
        processed += 1
        if now - last_log >= LOG_EVERY_S:
            described = [f"{t.label}#{t.id} " + ("?" if t.distance_m is None else f"~{t.distance_m:.2f}m")
                         + f" h={t.bbox[3] - t.bbox[1]:.0f}px" for t in targets]  # box height, for calibration
            log.info("targets: %s | %s", ", ".join(described) or "none",
                     selection_text(targets, selected, frame.shape[1]))
            last_log = now
    elapsed = time.monotonic() - start
    return (f"summary: seconds={elapsed:.1f} processed={processed} detect_fps={processed / max(elapsed, 1e-6):.1f} "
            f"tracks_seen={len(first_seen)} targets_now={len(targets)} "
            f"labels={sorted({t.label for t in targets})}")


def start_gemini(reader: LatestFrameReader):
    """Start the Gemini ranker, or return None (plain YOLO ranking) if the key or library is missing."""
    from vision.destinations import GEMINI_TIMEOUT_MS, GeminiRanker, load_api_key

    key = load_api_key()
    if not key:
        log.error("--gemini: no GEMINI_API_KEY in environment or .env; continuing without Gemini")
        return None
    from google import genai

    def newest_frame():
        snapshot = reader.latest()
        return None if snapshot is None else snapshot[0]

    ranker = GeminiRanker(genai.Client(api_key=key, http_options={"timeout": GEMINI_TIMEOUT_MS}), newest_frame)
    ranker.start()
    return ranker


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="YOLO + ByteTrack targets with frequencies and distance.")
    parser.add_argument("--source", default=os.environ.get("CAMERA_SOURCE", "1"), help="camera index, URL or file")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--hfov", type=float, default=load_hfov(), help="camera horizontal field of view, deg")
    parser.add_argument("--device", default="mps", help="mps (Apple GPU) or cpu")
    parser.add_argument("--seconds", type=float, default=None)
    parser.add_argument("--all-classes", action="store_true", help="show every COCO object, not just relevant ones")
    parser.add_argument("--gemini", action="store_true", help="rank targets with Gemini (needs GEMINI_API_KEY)")
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    if not os.path.exists(args.model):
        log.error("YOLO model not found at %s (set --model or YOLO_MODEL)", args.model)
        return 2
    from ultralytics import YOLO  # imported here so the pure functions and tests load fast

    source = parse_source(args.source)
    reader = LatestFrameReader(source, opener=open_capture)
    reader.start()
    log.info("source=%s model=%s device=%s", redact_url(source), args.model, args.device)
    model = YOLO(args.model)
    classes = None if args.all_classes else relevant_class_ids(model.names)
    ranker = start_gemini(reader) if args.gemini else None
    try:
        line = run(reader, model, args.hfov, args.device, args.seconds, classes, ranker)
    finally:
        if ranker is not None:
            ranker.stop()
        reader.stop()
        cv2.destroyAllWindows()
    print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
