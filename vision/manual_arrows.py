"""Manual gaze arrows (Prakhar, Sun Nov 15): four arrows at the edges of the camera view. Looking at one drives
that way at once, with no confirm; looking anywhere else sends nothing new (the chair stops).

Regions are fractions of the camera picture (the same coordinates as vision.object_select.to_view_point).
They are generous because webcam gaze is only good to a few percent of the screen.
"""

from __future__ import annotations

import numpy as np

from shared.protocol import MAX_SPEED, Target

# (x1, y1, x2, y2) as fractions of the camera picture
ARROW_REGIONS: dict[Target, tuple[float, float, float, float]] = {
    Target.FWD: (0.35, 0.00, 0.65, 0.17),
    Target.BACK: (0.35, 0.83, 0.65, 1.00),
    Target.LEFT: (0.00, 0.30, 0.12, 0.70),
    Target.RIGHT: (0.88, 0.30, 1.00, 0.70),
}
TURN_SHARE = 0.5  # spinning in place at full speed is violent; turns use half (as Keshav's keyboard_drive does)
TURN_SPEED = int(MAX_SPEED * TURN_SHARE)
# (left, right) wheel speeds; turns spin in place, matching chair.turn_left / chair.turn_right
ARROW_WHEELS: dict[Target, tuple[int, int]] = {
    Target.FWD: (MAX_SPEED, MAX_SPEED),
    Target.BACK: (-MAX_SPEED, -MAX_SPEED),
    Target.LEFT: (-TURN_SPEED, TURN_SPEED),
    Target.RIGHT: (TURN_SPEED, -TURN_SPEED),
}
ARROW_NAMES = {Target.FWD: "forward", Target.BACK: "backward", Target.LEFT: "rotate left", Target.RIGHT: "rotate right"}
ARROW_SIZE_FRAC = 0.07  # triangle size as a fraction of the screen width
IDLE_ALPHA, ACTIVE_ALPHA = 0.35, 0.85  # fill strength: faint until looked at, strong while driving that way


def arrow_at(view_point: tuple[float, float] | None) -> Target | None:
    """The arrow the gaze is on, or None."""
    if view_point is None:
        return None
    x, y = view_point
    return next((t for t, (x1, y1, x2, y2) in ARROW_REGIONS.items() if x1 <= x <= x2 and y1 <= y <= y2), None)


def _triangle(target: Target, cx: float, cy: float, half: float) -> np.ndarray:
    pts = {
        Target.FWD: [(cx, cy - half), (cx - half, cy + half), (cx + half, cy + half)],
        Target.BACK: [(cx, cy + half), (cx - half, cy - half), (cx + half, cy - half)],
        Target.LEFT: [(cx - half, cy), (cx + half, cy - half), (cx + half, cy + half)],
        Target.RIGHT: [(cx + half, cy), (cx - half, cy - half), (cx - half, cy + half)],
    }[target]
    return np.array(pts, np.int32)


def draw_arrows(cv2, canvas: np.ndarray, view_top: int, view_h: int, active: Target | None,
                fill_bgr: tuple[int, int, int], line_bgr: tuple[int, int, int]) -> np.ndarray:
    """The four arrows over the camera part of the screen (a new image; canvas is left alone)."""
    out = canvas.copy()
    w = canvas.shape[1]
    half = ARROW_SIZE_FRAC * w / 2
    for target, (x1, y1, x2, y2) in ARROW_REGIONS.items():
        cx, cy = (x1 + x2) / 2 * w, view_top + (y1 + y2) / 2 * view_h
        tri = _triangle(target, cx, cy, half)
        layer = out.copy()
        cv2.fillPoly(layer, [tri], fill_bgr)
        alpha = ACTIVE_ALPHA if target == active else IDLE_ALPHA
        out = cv2.addWeighted(layer, alpha, out, 1 - alpha, 0)
        cv2.polylines(out, [tri], True, line_bgr, 3 if target == active else 2, cv2.LINE_AA)
    return out
