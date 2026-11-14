"""Webcam gaze estimation, pure math (no camera, no mediapipe). The fallback if the EEG signal cannot be fixed.

How it works:
1. MediaPipe (vision/gaze_tracker.py) gives 478 face points per frame, incl. the centre of each iris.
2. eye_features(): where each iris sits between its eye corners (left/right) and above/below the corner line
   (up/down), plus where the nose sits between the cheeks / forehead-chin (head turn). 6 numbers.
3. Calibration: the rider looks at 9 dots; fit_calibration() learns a small polynomial map features -> screen point.
4. Every frame: predict() -> smooth() -> pick_region() with hysteresis -> which arrow / box is being looked at.
5. update_blink(): blinks shorter than BLINK_MAX_S keep the last gaze; longer closure = no gaze = chair stops.
All coordinates are normalized: image points and screen points go from 0 to 1.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, replace
from itertools import combinations_with_replacement
from pathlib import Path

import numpy as np

BLINK_MAX_S = 0.4  # a normal blink is 0.1-0.3 s; closures shorter than this keep the last gaze
CLOSED_FRACTION = 0.5  # eyes count as closed when openness drops below half of the rider's calibrated openness
SMOOTH_ALPHA = 0.3  # how much of each new gaze point to take (lower = steadier but laggier)
REGION_MARGIN = 0.03  # hysteresis: 3% of the screen inside a region to enter it, 3% outside to leave it
RIDGE_LAMBDA = 1e-2  # keeps the calibration fit from chasing noise
MIN_CALIBRATION_POINTS = 5


class LM:
    """MediaPipe face-mesh indices. Eye A is on the image's left (the rider's right eye), eye B on the right."""

    A_OUTER, A_INNER, A_UPPER, A_LOWER, A_IRIS = 33, 133, 159, 145, 468
    B_INNER, B_OUTER, B_UPPER, B_LOWER, B_IRIS = 362, 263, 386, 374, 473
    NOSE, CHEEK_A, CHEEK_B, FOREHEAD, CHIN = 1, 234, 454, 10, 152


# Screen regions for the 4 arrows (x1, y1, x2, y2), normalized. The centre belongs to no arrow: resting your eyes
# in the middle of the screen selects nothing, so the chair stays stopped.
ARROW_REGIONS: dict[str, tuple[float, float, float, float]] = {
    "FWD": (0.25, 0.0, 0.75, 0.33),
    "BACK": (0.25, 0.67, 0.75, 1.0),
    "LEFT": (0.0, 0.25, 0.25, 0.75),
    "RIGHT": (0.75, 0.25, 1.0, 0.75),
}


def _eye(p: np.ndarray, left: int, right: int, iris: int) -> tuple[float, float]:
    """Iris position within one eye: x 0..1 from the image-left corner to the image-right corner; y as a fraction
    of eye width above (-) or below (+) the line between the corners."""
    width = p[right, 0] - p[left, 0]
    mid_y = (p[left, 1] + p[right, 1]) / 2
    return (p[iris, 0] - p[left, 0]) / width, (p[iris, 1] - mid_y) / width


def eye_features(p: np.ndarray) -> np.ndarray:
    """6 numbers describing where the rider looks: [eyeA x, eyeA y, eyeB x, eyeB y, head x, head y]."""
    ax, ay = _eye(p, LM.A_OUTER, LM.A_INNER, LM.A_IRIS)
    bx, by = _eye(p, LM.B_INNER, LM.B_OUTER, LM.B_IRIS)
    head_x = (p[LM.NOSE, 0] - p[LM.CHEEK_A, 0]) / (p[LM.CHEEK_B, 0] - p[LM.CHEEK_A, 0]) - 0.5
    head_y = (p[LM.NOSE, 1] - p[LM.FOREHEAD, 1]) / (p[LM.CHIN, 1] - p[LM.FOREHEAD, 1]) - 0.5
    return np.array([ax, ay, bx, by, head_x, head_y])


def eye_openness(p: np.ndarray) -> float:
    """Lid gap divided by eye width, averaged over both eyes (~0.25 open, ~0.05 closed)."""
    a = (p[LM.A_LOWER, 1] - p[LM.A_UPPER, 1]) / (p[LM.A_INNER, 0] - p[LM.A_OUTER, 0])
    b = (p[LM.B_LOWER, 1] - p[LM.B_UPPER, 1]) / (p[LM.B_OUTER, 0] - p[LM.B_INNER, 0])
    return float((a + b) / 2)


@dataclass(frozen=True)
class Calibration:
    mean: tuple[float, ...]  # feature means (for standardizing)
    std: tuple[float, ...]
    weights: tuple[tuple[float, float], ...]  # one (x, y) weight pair per polynomial term
    open_ratio: float  # the rider's normal eye openness, measured during calibration


def _poly(z: np.ndarray) -> np.ndarray:
    """Degree-2 terms: 1, each feature, and every product of two features (28 terms for 6 features)."""
    pairs = [z[:, i] * z[:, j] for i, j in combinations_with_replacement(range(z.shape[1]), 2)]
    return np.column_stack([np.ones(len(z)), z, *pairs])


def fit_calibration(samples: Sequence[tuple[np.ndarray, tuple[float, float]]], open_ratio: float) -> Calibration:
    """samples: (features, (screen_x, screen_y)) pairs collected while the rider looked at known dots."""
    if len({target for _, target in samples}) < MIN_CALIBRATION_POINTS:
        raise ValueError(f"need at least {MIN_CALIBRATION_POINTS} different calibration points")
    feats = np.array([f for f, _ in samples])
    targets = np.array([t for _, t in samples], dtype=float)
    mean, std = feats.mean(axis=0), feats.std(axis=0)
    std = np.where(std < 1e-9, 1.0, std)  # a feature that never changed carries no information; avoid / 0
    design = _poly((feats - mean) / std)
    # Ridge regression: (X'X + lambda I) w = X'y, solved for x and y screen coordinates at once.
    weights = np.linalg.solve(design.T @ design + RIDGE_LAMBDA * np.eye(design.shape[1]), design.T @ targets)
    return Calibration(tuple(map(float, mean)), tuple(map(float, std)),
                       tuple((float(wx), float(wy)) for wx, wy in weights), float(open_ratio))


def predict(cal: Calibration, features: np.ndarray) -> tuple[float, float]:
    z = (np.asarray(features) - np.array(cal.mean)) / np.array(cal.std)
    x, y = (_poly(z[None, :]) @ np.array(cal.weights))[0]
    return float(np.clip(x, 0.0, 1.0)), float(np.clip(y, 0.0, 1.0))


def save_calibration(cal: Calibration, path: str | Path) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps({"mean": cal.mean, "std": cal.std, "weights": cal.weights,
                                      "open_ratio": cal.open_ratio}))


def load_calibration(path: str | Path) -> Calibration:
    data = json.loads(Path(path).read_text())
    return Calibration(tuple(data["mean"]), tuple(data["std"]), tuple(tuple(w) for w in data["weights"]),
                       float(data["open_ratio"]))


def smooth(prev: tuple[float, float] | None, point: tuple[float, float],
           alpha: float = SMOOTH_ALPHA) -> tuple[float, float]:
    """Exponential smoothing: move part of the way toward the new point (calms jitter)."""
    if prev is None:
        return point
    return prev[0] + alpha * (point[0] - prev[0]), prev[1] + alpha * (point[1] - prev[1])


def _inside(point: tuple[float, float], box: tuple[float, float, float, float], pad: float) -> bool:
    """pad > 0 grows the box, pad < 0 shrinks it."""
    return box[0] - pad <= point[0] <= box[2] + pad and box[1] - pad <= point[1] <= box[3] + pad


def pick_region(point: tuple[float, float], regions: dict[str, tuple[float, float, float, float]],
                current: str | None, margin: float = REGION_MARGIN) -> str | None:
    """Which region the gaze is in. Hysteresis: keep the current region until the gaze is clearly outside it,
    and enter a new one only when clearly inside, so the choice does not flicker at the borders."""
    if current in regions and _inside(point, regions[current], margin):
        return current
    for name, box in regions.items():
        if _inside(point, box, -margin):
            return name
    return None


@dataclass(frozen=True)
class BlinkState:
    last_point: tuple[float, float] | None = None
    closed_since: float | None = None


def update_blink(state: BlinkState, point: tuple[float, float] | None, closed: bool,
                 now: float) -> tuple[BlinkState, tuple[float, float] | None]:
    """Returns (new state, gaze point to use). Short blinks keep the last point; long closure or no face -> None."""
    if closed:
        since = state.closed_since if state.closed_since is not None else now
        held = state.last_point if now - since <= BLINK_MAX_S else None
        return replace(state, closed_since=since), held
    if point is None:  # no face found (turned away, out of frame): no gaze at once
        return BlinkState(), None
    return BlinkState(last_point=point), point
