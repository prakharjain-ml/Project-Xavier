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
RIDGE_LAMBDA = 0.05  # per sample: keeps the fit from chasing noise (scaled by the number of samples)
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
    degree: int = 2  # 1 = straight-line map (7 terms), 2 = curved map (28 terms)


def _poly(z: np.ndarray, degree: int = 2) -> np.ndarray:
    """Degree 1: [1, features] (7 terms). Degree 2: also every product of two features (28 terms)."""
    if degree == 1:
        return np.column_stack([np.ones(len(z)), z])
    pairs = [z[:, i] * z[:, j] for i, j in combinations_with_replacement(range(z.shape[1]), 2)]
    return np.column_stack([np.ones(len(z)), z, *pairs])


def fit_calibration(samples: Sequence[tuple[np.ndarray, tuple[float, float]]], open_ratio: float,
                    degree: int = 1) -> Calibration:
    """samples: (features, (screen_x, screen_y)) pairs collected while the rider looked at known dots."""
    if len({target for _, target in samples}) < MIN_CALIBRATION_POINTS:
        raise ValueError(f"need at least {MIN_CALIBRATION_POINTS} different calibration points")
    feats = np.array([f for f, _ in samples])
    targets = np.array([t for _, t in samples], dtype=float)
    mean, std = feats.mean(axis=0), feats.std(axis=0)
    std = np.where(std < 1e-9, 1.0, std)  # a feature that never changed carries no information; avoid / 0
    design = _poly((feats - mean) / std, degree)
    # Ridge regression: (X'X + lambda*n I) w = X'y, solved for x and y screen coordinates at once. lambda is
    # scaled by the sample count n so the smoothing strength does not vanish as more samples are collected.
    penalty = RIDGE_LAMBDA * len(design) * np.eye(design.shape[1])
    penalty[0, 0] = 0.0  # never shrink the constant term (the screen centre offset)
    weights = np.linalg.solve(design.T @ design + penalty, design.T @ targets)
    return Calibration(tuple(map(float, mean)), tuple(map(float, std)),
                       tuple((float(wx), float(wy)) for wx, wy in weights), float(open_ratio), degree)


def cross_validate(samples: Sequence[tuple[np.ndarray, tuple[float, float]]], open_ratio: float) -> dict[int, float]:
    """Leave-one-dot-out error for the straight (1) and curved (2) map: fit on 8 dots, predict the 9th.

    Returns {degree: mean distance between predicted and true point, as a fraction of the screen}. This shows
    how the map does on gaze positions it was NOT trained on, which is what driving needs.
    """
    targets = sorted({t for _, t in samples})
    errors: dict[int, float] = {}
    for degree in (1, 2):
        distances = []
        for held_out in targets:
            train = [s for s in samples if s[1] != held_out]
            cal = fit_calibration(train, open_ratio, degree)
            distances += [float(np.hypot(*(np.array(predict(cal, f)) - np.array(t))))
                          for f, t in samples if t == held_out]
        errors[degree] = float(np.mean(distances))
    return errors


def predict(cal: Calibration, features: np.ndarray) -> tuple[float, float]:
    z = (np.asarray(features) - np.array(cal.mean)) / np.array(cal.std)
    x, y = (_poly(z[None, :], cal.degree) @ np.array(cal.weights))[0]
    return float(np.clip(x, 0.0, 1.0)), float(np.clip(y, 0.0, 1.0))


def save_calibration(cal: Calibration, path: str | Path) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps({"mean": cal.mean, "std": cal.std, "weights": cal.weights,
                                      "open_ratio": cal.open_ratio, "degree": cal.degree}))


def load_calibration(path: str | Path) -> Calibration:
    data = json.loads(Path(path).read_text())
    return Calibration(tuple(data["mean"]), tuple(data["std"]), tuple(tuple(w) for w in data["weights"]),
                       float(data["open_ratio"]), int(data.get("degree", 2)))


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


@dataclass(frozen=True)
class GazeState:
    blink: BlinkState = BlinkState()
    smoothed: tuple[float, float] | None = None


@dataclass(frozen=True)
class GazeSample:
    """One gaze reading sent to the app. point is None when there is no usable gaze (no face / eyes closed)."""

    point: tuple[float, float] | None
    closed: bool
    face: bool
    t: float  # time.monotonic() when the frame was processed

    @property
    def x(self) -> float | None:
        return None if self.point is None else self.point[0]

    @property
    def y(self) -> float | None:
        return None if self.point is None else self.point[1]


def gaze_step(points: np.ndarray | None, cal: Calibration, state: GazeState,
              now: float) -> tuple[GazeState, GazeSample]:
    """One camera frame -> one GazeSample. points is the (478, 2) landmark array, or None if no face was found."""
    if points is None:
        blink, _ = update_blink(state.blink, None, closed=False, now=now)
        return GazeState(blink, None), GazeSample(None, False, False, now)
    closed = eye_openness(points) < CLOSED_FRACTION * cal.open_ratio
    raw = None if closed else predict(cal, eye_features(points))
    blink, held = update_blink(state.blink, raw, closed, now)
    if held is None:
        return GazeState(blink, None), GazeSample(None, closed, True, now)
    if closed and state.smoothed is not None:
        smoothed = state.smoothed  # during a blink keep the last SMOOTHED point (no jump at every blink)
    else:
        smoothed = smooth(state.smoothed, held)
    return GazeState(blink, smoothed), GazeSample(smoothed, closed, True, now)


# ---------------------------------------------------------------- wire format (tracker process -> app, UDP)
# docs/INTERFACES.md transport rule: every message carries "v" and "type"; anything invalid is dropped whole.
GAZE_MESSAGE_TYPE = "GazeSample"
GAZE_MESSAGE_VERSION = 1


def encode_gaze_message(sample: GazeSample) -> bytes:
    return json.dumps({"v": GAZE_MESSAGE_VERSION, "type": GAZE_MESSAGE_TYPE, "x": sample.x, "y": sample.y,
                       "closed": sample.closed, "face": sample.face}).encode()


def decode_gaze_message(raw: bytes, now: float) -> GazeSample | None:
    """Parse one datagram. Timestamped with the RECEIVER's clock (`now`) so the two processes' clocks never
    have to agree; localhost delivery takes well under a millisecond."""
    try:
        data = json.loads(raw)
        if data["v"] != GAZE_MESSAGE_VERSION or data["type"] != GAZE_MESSAGE_TYPE:
            return None
        x, y, closed, face = data["x"], data["y"], data["closed"], data["face"]
        if not isinstance(closed, bool) or not isinstance(face, bool):
            return None
        point = None if x is None or y is None else (float(x), float(y))
    except (ValueError, KeyError, TypeError):
        return None
    return GazeSample(point, closed, face, now)
