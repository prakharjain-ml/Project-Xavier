"""Calm the screen: a steadier gaze cursor and outlines that glide instead of jumping.

1. one_euro(): the One Euro filter (Casiez et al., CHI 2012), the standard filter for pointers driven by noisy
   sensors. It smooths hard while the point is nearly still (a fixation: the shake disappears) and smooths less
   as the point moves fast (a glance to another object: little lag). EyeTrax already smooths a little; this
   sits on top of it.
2. glide_tracks(): detection runs about 7 times a second, so outlines would jump 7 times a second. Each object's
   drawn box moves a share of the way toward its newest detected box on every screen update instead.

The smoothed gaze point is used for BOTH the cursor and choosing the object under it, so what the rider sees is
what selects (a shaky raw point could leave the object while the cursor sits still on it). It adds about 0.1 s
on a fast glance; no gaze at all still means no point at once, so the stop on lost gaze is not delayed.
glide_tracks() is drawing only: selection and driving keep using the real detections.
Pure functions: state in, new state out; inputs are never modified."""

from __future__ import annotations

import math
from dataclasses import dataclass, replace

from vision.detect_track import Track

# One Euro settings for gaze in screen fractions (0..1). Lower MIN_CUTOFF_HZ = steadier fixations but more lag;
# higher BETA = less lag on fast glances. Swept on synthetic gaze (2% shake, 30 Hz):
#   0.3 / 1.0: shake 0.23 of raw, glance 0.10 s, slow-sweep lag 90 ms (Prakhar: steady but laggy)
#   0.6 / 1.5: shake 0.31 of raw, glance 0.10 s, slow-sweep lag 66 ms  <- chosen; EyeTrax smooths too
#   1.0 / 4.0: shake 0.45 of raw, glance 0.03 s, slow-sweep lag 37 ms
MIN_CUTOFF_HZ = 0.6
BETA = 1.5
DERIVATIVE_CUTOFF_HZ = 1.0
RESET_AFTER_S = 0.5  # gaze missing this long (eyes closed, face lost): start fresh instead of gliding from the old spot
GLIDE_SHARE = 0.35  # each screen update, a drawn box moves this share of the way to its newest detected box


@dataclass(frozen=True)
class EuroState:
    point: tuple[float, float] | None = None  # last smoothed point
    speed: tuple[float, float] = (0.0, 0.0)  # smoothed velocity, screen fractions per second
    t: float | None = None  # time of the last point


def _alpha(cutoff_hz: float, dt: float) -> float:
    """Share of the new value to take: a low-pass filter with this cutoff frequency, for a step of dt seconds."""
    tau = 1.0 / (2.0 * math.pi * cutoff_hz)
    return 1.0 / (1.0 + tau / dt)


def one_euro(state: EuroState, point: tuple[float, float] | None, t: float) -> tuple[EuroState, tuple[float, float] | None]:
    """Feed the newest raw gaze point (or None when there is none). Returns (new state, point to draw)."""
    if point is None:
        return state, None  # nothing to draw; the state is kept so a blink does not restart the filter
    if state.point is None or state.t is None or not 0.0 < t - state.t <= RESET_AFTER_S:
        return EuroState(point, (0.0, 0.0), t), point
    dt = t - state.t
    raw_speed = ((point[0] - state.point[0]) / dt, (point[1] - state.point[1]) / dt)
    a_speed = _alpha(DERIVATIVE_CUTOFF_HZ, dt)
    speed = tuple(s + a_speed * (r - s) for s, r in zip(state.speed, raw_speed))
    cutoff = MIN_CUTOFF_HZ + BETA * math.hypot(*speed)  # the faster the gaze moves, the less it is smoothed
    a = _alpha(cutoff, dt)
    smoothed = tuple(p + a * (n - p) for p, n in zip(state.point, point))
    return EuroState(smoothed, speed, t), smoothed


def glide_tracks(drawn: dict[int, Track], latest: list[Track], share: float = GLIDE_SHARE) -> dict[int, Track]:
    """Drawn copies of the latest detections, each moved `share` of the way from where it was drawn last time.
    New objects appear where they are; objects no longer detected disappear at once (never draw a ghost)."""
    result: dict[int, Track] = {}
    for track in latest:
        before = drawn.get(track.id)
        if before is None:
            result[track.id] = track
            continue
        box = tuple(b + share * (n - b) for b, n in zip(before.bbox, track.bbox))
        outline = None
        if track.outline is not None:
            # Move and scale the newest outline so it fits the glided box (same shape, smooth position).
            (x1, y1, x2, y2), (gx1, gy1, gx2, gy2) = track.bbox, box
            sx = (gx2 - gx1) / (x2 - x1) if x2 > x1 else 1.0
            sy = (gy2 - gy1) / (y2 - y1) if y2 > y1 else 1.0
            outline = (track.outline - (x1, y1)) * (sx, sy) + (gx1, gy1)
        result[track.id] = replace(track, bbox=box, outline=outline)
    return result
