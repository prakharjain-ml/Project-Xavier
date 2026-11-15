"""Gaze calibration + accuracy check. Run on the demo laptop, rider sitting where they will sit on the chair.

    python -m vision.gaze_calibrate --eye-camera 0

1. Look at each of 9 dots (2 s each) while keeping your head still. That fits the gaze map.
2. Validation: each arrow region lights up for 3 s; look at it. A live cursor shows where we think you look.
3. Prints `summary: ... accuracy=NN%` = how often the gaze landed in the right region (target >= 85%).
Saves the calibration to data/raw/gaze_calibration.json (gitignored), which `app.py --gaze` loads.
OpenCV window only (no pygame), so it can import cv2 safely. ESC quits at any time.
"""

from __future__ import annotations

import argparse
import statistics
import sys
import time
from collections.abc import Sequence

import numpy as np

from interface import screens, window
from vision.gaze import (
    ARROW_REGIONS,
    GazeState,
    cross_validate,
    eye_features,
    eye_openness,
    fit_calibration,
    gaze_step,
    pick_region,
    save_calibration,
)
from vision.gaze_tracker import CALIBRATION_PATH, FaceLandmarkSource

WINDOW = "gaze calibration"
CANVAS_W, CANVAS_H = 1280, 800  # drawn at this size and stretched to the full screen: positions stay fractions
DOT_S, DOT_SETTLE_S = 2.0, 0.7  # each dot is shown 2 s; the first 0.7 s (eyes still moving there) is ignored
REGION_S, REGION_SETTLE_S = 3.0, 1.0
BLINK_FRACTION = 0.5  # samples with eyes less than half as open as usual are blinks and are dropped
ESC, SPACE = 27, 32


def calibration_targets() -> list[tuple[float, float]]:
    """3 x 3 grid near the screen edges; zig-zag order so the eyes never jump across the whole screen."""
    rows = [0.1, 0.5, 0.9]
    return [(x, y) for i, y in enumerate(rows) for x in (rows if i % 2 == 0 else rows[::-1])]


def drop_blinks(samples: Sequence[tuple[np.ndarray, tuple[float, float], float]]):
    """samples: (features, target, openness). Returns (kept (features, target) pairs, typical open ratio)."""
    open_ratio = statistics.median(s[2] for s in samples)
    kept = [(f, t) for f, t, openness in samples if openness >= BLINK_FRACTION * open_ratio]
    return kept, open_ratio


def region_accuracy(picks: dict[str, list[str | None]]) -> tuple[dict[str, float], float]:
    """picks: for each region the rider was asked to look at, the region we detected on each frame."""
    per = {name: (sum(p == name for p in got) / len(got) if got else 0.0) for name, got in picks.items()}
    total = sum(len(got) for got in picks.values())
    overall = sum(sum(p == name for p in got) for name, got in picks.items()) / total if total else 0.0
    return per, overall


def format_summary(samples: int, per: dict[str, float], overall: float) -> str:
    regions = " ".join(f"{name}={value:.0%}" for name, value in per.items())
    return f"summary: calibration_samples={samples} accuracy={overall:.0%} {regions}"


def _canvas(cv2, text: str = ""):
    img = np.zeros((CANVAS_H, CANVAS_W, 3), np.uint8)
    if text:
        cv2.putText(img, text, (40, 60), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (200, 200, 200), 2)
    return img


def _px(point: tuple[float, float]) -> tuple[int, int]:
    return int(point[0] * CANVAS_W), int(point[1] * CANVAS_H)


def _show(cv2, img) -> int:
    window.show(cv2, WINDOW, img)  # stretched to the real screen size, so dot positions stay screen fractions
    return cv2.waitKey(1) & 0xFF


def wait_for_space(cv2, source: FaceLandmarkSource) -> bool:
    while True:
        _, points = source.read()
        img = screens.face_check(CANVAS_W, CANVAS_H, points is not None, None, "Eye calibration",
                                 "Sit as you will in the chair. Keep your head still and look at each dot.",
                                 (("SPACE", "Start"), ("ESC", "Quit")))
        key = _show(cv2, img)
        if key == ESC:
            return False
        if key == SPACE and points is not None:
            return True


def collect_calibration(cv2, source: FaceLandmarkSource):
    samples = []
    targets = calibration_targets()
    for index, target in enumerate(targets):
        start = time.monotonic()
        while (elapsed := time.monotonic() - start) < DOT_S:
            _, points = source.read()
            radius = 22 - 14 * elapsed / DOT_S  # shrinking dot pulls the eyes to its centre
            # Same timing as before: the ring fills only once samples are being kept (after DOT_SETTLE_S).
            capturing = elapsed > DOT_SETTLE_S
            phase_progress = (elapsed - DOT_SETTLE_S) / (DOT_S - DOT_SETTLE_S) if capturing else elapsed / DOT_SETTLE_S
            img = screens.calibration_target(CANVAS_W, CANVAS_H, _px(target), "capture" if capturing else "pulse",
                                             phase_progress, index, len(targets), radius)
            if _show(cv2, img) == ESC:
                return None
            if elapsed > DOT_SETTLE_S and points is not None:
                samples.append((eye_features(points), target, eye_openness(points)))
    return samples


def validate(cv2, source: FaceLandmarkSource, cal, points_log: list | None = None) -> dict[str, list[str | None]] | None:
    picks: dict[str, list[str | None]] = {}
    for name, box in ARROW_REGIONS.items():
        state, current, got, start = GazeState(), None, [], time.monotonic()
        while (elapsed := time.monotonic() - start) < REGION_S:
            _, points = source.read()
            state, sample = gaze_step(points, cal, state, time.monotonic())
            current = pick_region(sample.point, ARROW_REGIONS, current) if sample.point else None
            img = screens.region_check(CANVAS_W, CANVAS_H, (*_px(box[:2]), *_px(box[2:])),
                                       _px(sample.point) if sample.point else None, current == name, name)
            if _show(cv2, img) == ESC:
                return None
            if elapsed > REGION_SETTLE_S:
                got.append(current)
                if points_log is not None:
                    points_log.append((name, sample.point))
        picks[name] = got
    return picks


def save_raw(calibration_path: str, raw, points_log) -> None:
    """Keep the raw run (gitignored data/raw/) so a bad calibration can be analysed instead of guessed at."""
    out = calibration_path.replace(".json", "_raw.npz")
    np.savez(out, features=np.array([f for f, _, _ in raw]), targets=np.array([t for _, t, _ in raw]),
             openness=np.array([o for _, _, o in raw]),
             validation_region=np.array([name for name, _ in points_log]),
             validation_point=np.array([p if p is not None else (np.nan, np.nan) for _, p in points_log]))
    print(f"raw data saved to {out}")


def run_calibration(cv2, source: FaceLandmarkSource, out: str) -> float | None:
    """Full calibration in the current window: wait for SPACE, 9 dots, fit, save, 4-region check.
    Returns overall accuracy (0-1), or None if the rider cancelled or no face was seen."""
    window.open_fullscreen(cv2, WINDOW)
    if not wait_for_space(cv2, source):
        return None
    raw = collect_calibration(cv2, source)
    if not raw:
        print("calibration cancelled or no face seen")
        return None
    samples, open_ratio = drop_blinks(raw)
    # Pick the map that predicts unseen dots best (fit on 8 dots, test on the 9th, for every dot).
    errors = cross_validate(samples, open_ratio)
    degree = min(errors, key=errors.get)
    print(f"leave-one-dot-out error: straight={errors[1]:.3f} curved={errors[2]:.3f} (screen fraction) "
          f"-> using {'straight' if degree == 1 else 'curved'}")
    cal = fit_calibration(samples, open_ratio, degree)
    save_calibration(cal, out)
    print(f"saved calibration to {out} ({len(samples)} samples, open ratio {open_ratio:.2f})")
    points_log: list = []
    picks = validate(cv2, source, cal, points_log)
    save_raw(out, raw, points_log)
    if picks is None:
        return None
    per, overall = region_accuracy(picks)
    print(format_summary(len(samples), per, overall))
    return overall


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Calibrate webcam gaze and measure its accuracy.")
    parser.add_argument("--eye-camera", type=int, default=0, help="camera index that sees the rider's face")
    parser.add_argument("--out", default=CALIBRATION_PATH)
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    import cv2

    source = FaceLandmarkSource(args.eye_camera)
    try:
        return 0 if run_calibration(cv2, source, args.out) is not None else 1
    finally:
        source.close()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    raise SystemExit(main())
