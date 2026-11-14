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
import logging
import math
import os
import sys
import time
from collections.abc import Sequence
from dataclasses import dataclass

import cv2
import numpy as np

from vision.camera_source import LatestFrameReader, open_capture, parse_source, redact_url

log = logging.getLogger("vision.detect_track")

# TODO(task 1.3): import these from shared/protocol.py once it exists; values copied from docs/INTERFACES.md.
TARGET_FREQS_HZ = (60 / 9, 60 / 7, 12.0, 15.0)
MAX_TARGETS = 4
DEFAULT_MODEL = os.path.expanduser(os.environ.get("YOLO_MODEL", "~/hp26-models/yolo11n.pt"))
DEFAULT_HFOV_DEG = 70.0  # horizontal field of view guess for a phone/webcam; calibrate with --hfov
MIN_CONF = 0.4  # ignore detections YOLO is less sure about
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


def assign_frequencies(target_ids: Sequence[int], previous: dict[int, float]) -> dict[int, float]:
    """Return a new id->frequency map. Objects keep their frequency while tracked; new ones get a free one."""
    kept = {tid: previous[tid] for tid in target_ids if tid in previous}
    free = [f for f in TARGET_FREQS_HZ if f not in kept.values()]
    new_ids = [tid for tid in target_ids if tid not in kept]
    return {**kept, **dict(zip(new_ids, free))}


def steering_offset(bbox: tuple[float, float, float, float], frame_width: int) -> float:
    """-1 = far left, 0 = straight ahead, +1 = far right. The future go-to-target steers to make this 0."""
    center_x = (bbox[0] + bbox[2]) / 2
    return (center_x - frame_width / 2) / (frame_width / 2)


def detect(model, frame: np.ndarray, focal_px: float, device: str, classes: list[int] | None) -> list[Track]:
    result = model.track(frame, persist=True, tracker="bytetrack.yaml", device=device, conf=MIN_CONF,
                         classes=classes, verbose=False)[0]
    if result.boxes is None or result.boxes.id is None:  # no confirmed tracks this frame
        return []
    tracks = []
    for tid, cls, conf, box in zip(result.boxes.id.tolist(), result.boxes.cls.tolist(),
                                   result.boxes.conf.tolist(), result.boxes.xyxy.tolist()):
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
        if ranker is None:
            targets = pick_targets(tracks, first_seen)
        else:  # Gemini suggestions first, then steadiest YOLO objects (see vision/destinations.py)
            from vision.destinations import rank_targets
            targets = rank_targets(tracks, ranker.latest(), first_seen)
        freqs = assign_frequencies([t.id for t in targets], freqs)
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
    parser.add_argument("--hfov", type=float, default=DEFAULT_HFOV_DEG, help="camera horizontal field of view, deg")
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
