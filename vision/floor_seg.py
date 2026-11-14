"""Find the floor in a camera frame by its colour, starting from floor we are sure about.

Why: Gemini's floor outline turned out too rough to plan on (on the hall test frame it returned only a strip
along the bottom of the picture). The floor's edge is something the picture itself shows precisely.

How: the bottom band of the image is the floor nearest the chair (wherever no detected object covers it). Learn
that floor's colour, mark every pixel of similar colour below the horizon, and keep only the part connected
to the bottom band. A wall or cabinet has a different colour; a detected object is removed by its outline.
Known limits: a wall the same colour as the floor, a patterned floor, or a hard shadow will fool it, so this
is still an estimate. Gemini's no-go zones and the chair's ultrasonic stop sit on top of it.
Pure function: image in, mask out."""

from __future__ import annotations

import cv2
import numpy as np

WORK_W = 320  # work on a small copy: floor is a big region, and small is fast and less noisy
SEED_BAND = 0.08  # the bottom 8% of the image is taken as known floor (where no object covers it)
MIN_SEED_PX = 50  # fewer known-floor pixels than this: the bottom of the view is blocked, so no floor at all
MAX_COLOUR_DIST = 3.5  # how many "typical variations" from the known floor colour still counts as floor
# Floor farther away is lit differently from the floor at our feet, so allow at least this much variation
# (variance in Lab units) in brightness and in the two colour channels, however uniform the bottom band is.
MIN_VARIANCE = np.array([250.0, 16.0, 16.0])
BLUR_PX = 5  # smooths carpet speckle before comparing colours


def colour_floor(frame: np.ndarray, objects: np.ndarray, horizon_row: float) -> np.ndarray:
    """Bool mask (frame height x width) of floor: similar in colour to the floor at the bottom of the image,
    connected to it, below the horizon, and not covered by a detected object."""
    height, width = frame.shape[:2]
    scale = WORK_W / width
    small = cv2.resize(frame, (WORK_W, max(1, round(height * scale))), interpolation=cv2.INTER_AREA)
    # Lab separates brightness (L) from colour (a, b), so a shaded patch of the same carpet stays close.
    lab = cv2.cvtColor(cv2.medianBlur(small, BLUR_PX), cv2.COLOR_BGR2LAB).astype(np.float32)
    rows, cols = lab.shape[:2]
    blocked = cv2.resize(objects.astype(np.uint8), (cols, rows), interpolation=cv2.INTER_NEAREST).astype(bool)
    seed = np.zeros((rows, cols), bool)
    seed[int(rows * (1 - SEED_BAND)):] = True
    seed &= ~blocked
    if seed.sum() < MIN_SEED_PX:
        return np.zeros((height, width), bool)
    samples = lab[seed]
    spread = np.cov(samples.T) + np.diag(MIN_VARIANCE)
    offset = lab - samples.mean(axis=0)
    # Mahalanobis distance: colour difference measured in units of the floor's own variation.
    distance_sq = np.einsum("...i,ij,...j->...", offset, np.linalg.inv(spread), offset)
    alike = (distance_sq < MAX_COLOUR_DIST ** 2) & ~blocked
    alike[: max(0, int(horizon_row * scale) + 1)] = False  # nothing at or above the horizon is floor
    alike = cv2.morphologyEx(alike.astype(np.uint8), cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))  # drop specks
    _count, labels = cv2.connectedComponents(alike, connectivity=4)
    reachable = np.unique(labels[seed & (alike > 0)])  # the patches that touch the known floor
    floor = np.isin(labels, reachable[reachable > 0])
    return cv2.resize(floor.astype(np.uint8), (width, height), interpolation=cv2.INTER_NEAREST).astype(bool)
