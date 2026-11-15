"""Where to float the navigation chevrons over the camera picture (Google Maps Live View style).

The route from the A* planner is a list of floor points in metres in the chair's frame (x forward, y left).
Big upright chevrons are placed along it at a fixed spacing, floating above the floor, each pointing the way
the route goes at that spot. They are drawn by vision/hud.py; this module only does the geometry.

Why floating instead of painted on the floor: a painted path has to line up with the real floor exactly, which
needs an accurate camera height and tilt. A chevron in the air still points the right way when those numbers
are a little off, and it reads from across the room.
Look inspired by the "Direction Chevron" model by Polyfork (CC BY 4.0): a flat rounded chevron with a rim.
Pure functions: no drawing, no camera, no clock."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

GUIDE_COUNT = 5          # at most this many chevrons
GUIDE_GAP_M = 0.55       # spacing along the route
GUIDE_START_M = 1.3      # first chevron this far along the route from the chair (nearer ones are below the picture)
GUIDE_END_CLEAR_M = 0.25 # no chevron in the last 30 cm before the stop point
GUIDE_LIFT_M = 0.35      # chevrons float this high above the floor
GUIDE_WIDTH_M = 0.3      # real width of one chevron
DIRECTION_STEP_M = 0.3   # how far ahead along the route the pointing direction is measured
MAX_TURN_RAD = math.radians(100)  # never point backwards (the planner never reverses)
# Perspective squashes a turn: a route bending right still runs mostly "up" the picture. Turning the chevrons
# a bit further than the true screen direction makes the way to go readable at a glance (as Live View does).
ANGLE_GAIN = 1.5
MIN_SIZE_PX = 14.0       # smaller than this is too far away to read: skip
MAX_SIZE_FRAC = 0.13     # never wider than this share of the picture (a near chevron would cover the view)
EDGE_SLACK = 0.15        # a chevron may sit this fraction of the frame outside it and still be drawn
MIN_DEPTH_M = 0.05


@dataclass(frozen=True)
class Guide:
    center: tuple[float, float]  # pixels
    size: float                  # chevron width in pixels (perspective: nearer = bigger)
    angle: float                 # radians; 0 = pointing straight ahead (up the screen), positive = to the left
    depth: float                 # metres along the camera's view: draw far ones first
    order: int                   # 0 = nearest chevron, used for the gentle highlight that runs along the row


def project_points(points_xyz: np.ndarray, frame_w: int, frame_h: int, hfov_deg: float, cam_h: float,
                   pitch_deg: float) -> tuple[np.ndarray, np.ndarray]:
    """(N, 3) points [forward, left, up] in metres -> ((N, 2) pixels, (N,) depth). NaN where behind the camera.
    Same pinhole camera as vision/floor.project_floor, with a height: the camera sits cam_h above the floor."""
    pts = np.asarray(points_xyz, dtype=float).reshape(-1, 3)
    focal = (frame_w / 2) / math.tan(math.radians(hfov_deg) / 2)
    tilt = math.radians(pitch_deg)
    x, y, below = pts[:, 0], pts[:, 1], cam_h - pts[:, 2]  # below = how far under the camera the point is
    depth = x * math.cos(tilt) + below * math.sin(tilt)
    down = -x * math.sin(tilt) + below * math.cos(tilt)
    with np.errstate(divide="ignore", invalid="ignore"):
        pixels = np.stack([frame_w / 2 + focal * (-y) / depth, frame_h / 2 + focal * down / depth], axis=1)
    pixels[depth < MIN_DEPTH_M] = np.nan
    return pixels, depth


def route_length_m(route_m: np.ndarray) -> float:
    """Distance from the chair along the route to its stop point (the first leg starts at the chair, (0, 0))."""
    path = np.vstack([[0.0, 0.0], np.asarray(route_m, float).reshape(-1, 2)])
    return float(np.linalg.norm(np.diff(path, axis=0), axis=1).sum())


def _point_at(path: np.ndarray, along: np.ndarray, s: float) -> tuple[np.ndarray, np.ndarray]:
    """Point at arc length s along the path, and the unit direction of the path there."""
    i = int(np.clip(np.searchsorted(along, s, side="right") - 1, 0, len(path) - 2))
    seg = path[i + 1] - path[i]
    length = float(np.linalg.norm(seg))
    share = 0.0 if length == 0 else (s - along[i]) / length
    return path[i] + share * seg, seg / max(length, 1e-9)


def place_guides(route_m: np.ndarray | None, frame_w: int, frame_h: int, hfov_deg: float, cam_h: float,
                 pitch_deg: float) -> tuple[Guide, ...]:
    """Chevrons for one route, nearest first. Empty when there is no route or nothing of it can be seen."""
    if route_m is None:
        return ()
    visible = np.asarray(route_m, float).reshape(-1, 2)
    if len(visible) == 0 or not np.isfinite(visible).all():
        return ()
    path = np.vstack([[0.0, 0.0], visible])
    along = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(path, axis=0), axis=1))])
    # Along the whole route from the chair, not only its visible part: a route of one long leg (the floor near the
    # chair is never seen) still gets chevrons. Any that would land outside the picture are skipped below.
    first, last = GUIDE_START_M, float(along[-1]) - GUIDE_END_CLEAR_M
    guides: list[Guide] = []
    for k in range(GUIDE_COUNT):
        s = first + k * GUIDE_GAP_M
        if s > last:
            break
        at, heading = _point_at(path, along, s)
        ahead, _ = _point_at(path, along, min(s + DIRECTION_STEP_M, float(along[-1])))
        side = np.array([-heading[1], heading[0]])  # unit vector to the left of the route
        world = np.array([[*at, GUIDE_LIFT_M], [*(at + side * GUIDE_WIDTH_M / 2), GUIDE_LIFT_M],
                          [*ahead, GUIDE_LIFT_M]])
        px, depth = project_points(world, frame_w, frame_h, hfov_deg, cam_h, pitch_deg)
        if np.isnan(px).any():
            continue
        centre, size = px[0], 2.0 * float(np.linalg.norm(px[1] - px[0]))
        if size < MIN_SIZE_PX or not _on_screen(centre, frame_w, frame_h):
            continue
        size = min(size, MAX_SIZE_FRAC * frame_w)
        # Point the way the route heads compared with where the chair faces now: straight ahead = up, a route
        # going right = tilted right. (The on-screen direction of a straight leg from the chair is always "up"
        # the picture, which would hide the turn the chair has to make.) Left = positive, as on screen.
        travel = ahead - at
        angle = float(np.clip(ANGLE_GAIN * math.atan2(travel[1], travel[0]), -MAX_TURN_RAD, MAX_TURN_RAD))
        guides.append(Guide((float(centre[0]), float(centre[1])), size, angle, float(depth[0]), len(guides)))
    return tuple(guides)


def _on_screen(point: np.ndarray, frame_w: int, frame_h: int) -> bool:
    x, y = point
    return -EDGE_SLACK * frame_w <= x <= (1 + EDGE_SLACK) * frame_w and -EDGE_SLACK * frame_h <= y <= (1 + EDGE_SLACK) * frame_h
