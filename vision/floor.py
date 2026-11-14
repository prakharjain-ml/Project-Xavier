"""Floor point (metres, chair frame) -> pixel in the forward camera image (pinhole camera model).

The camera sits cam_height_m above the floor and is tilted down by pitch_deg. A floor point x metres ahead and
y metres to the left is (x, y, -height) relative to the camera; rotating by the tilt and dividing by depth gives
its pixel. That is what lets us draw the planned path ON the floor in the live video.
VERIFY the two numbers on the chair (tape measure for the height; the pitch from where the floor meets the image).
"""

from __future__ import annotations

import math

import numpy as np

MIN_DEPTH_M = 0.05  # points closer than this to the camera plane (or behind it) cannot be drawn


def project_floor(points: np.ndarray, frame_w: int, frame_h: int, hfov_deg: float, cam_height_m: float,
                  pitch_deg: float) -> np.ndarray:
    """(N, 2) floor points [x forward, y left] -> (N, 2) pixels [u, v]; NaN where the point can't be seen."""
    pts = np.asarray(points, dtype=float).reshape(-1, 2)
    focal = (frame_w / 2) / math.tan(math.radians(hfov_deg) / 2)
    tilt = math.radians(pitch_deg)
    x, y = pts[:, 0], pts[:, 1]
    depth = x * math.cos(tilt) + cam_height_m * math.sin(tilt)  # along the camera's viewing direction
    down = -x * math.sin(tilt) + cam_height_m * math.cos(tilt)  # below the camera's centre line
    with np.errstate(divide="ignore", invalid="ignore"):
        u = frame_w / 2 + focal * (-y) / depth  # left of the chair = left in the image
        v = frame_h / 2 + focal * down / depth
    out = np.stack([u, v], axis=1)
    out[depth < MIN_DEPTH_M] = np.nan
    return out
