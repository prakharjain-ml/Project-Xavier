"""Follow a planned route: turn "the shortest safe path on the floor" into a speed and a turn rate.

Method: pure pursuit. Pick the point on the route a fixed distance ahead (the look-ahead point) and steer along
the circle that passes through the chair and that point. Do this again on every camera frame with a freshly
planned route, so errors do not build up: the chair is always chasing a point on the newest route.

The route is in the chair's own frame: x metres forward, y metres to the left, the chair at (0, 0) facing +x.
It starts at the nearest floor the camera can see; the short unseen strip between the chair and that floor is
treated as a straight line.

This module only proposes a motion. The safety state machine (control/state_machine.py) still decides whether
the chair may move at all, and the ESP32's ultrasonic stop and watchdog are untouched.
No route, a broken route, or any doubt -> (0, 0): stop is the default.
Pure functions: no camera, no clock, no I/O."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from control.navigation import NavConfig


@dataclass(frozen=True)
class FollowConfig:
    # Chase the route point this far ahead. Shorter cuts corners less but reacts harder to noise. In simulation
    # (ideal chair, 38 degree corners) the worst distance off the route was 6.5 cm at 0.5 m, 8.4 cm at 0.6 m,
    # 15.6 cm at 0.9 m. vision/route_scene.FOLLOW_MARGIN_M reserves room for this error when planning.
    lookahead_m: float = 0.6
    stop_short_m: float = 0.5  # arrived when this much route is left (the route ends right at the object's foot)
    turn_in_place_deg: float = 55.0  # look-ahead point further off to the side than this: turn first, then drive
    turn_rate_frac: float = 0.6  # turning on the spot uses this share of the top turn rate
    slow_down_m: float = 1.0  # over the last metre before the stop point, speed falls in a straight line
    min_speed: float = 0.2  # ... but not below this (slower commands sit in the motor board's dead band)


def _lookahead_point(route: np.ndarray, distance: float) -> np.ndarray:
    """The point `distance` metres along the route from its start (the route's end if it is shorter)."""
    steps = np.linalg.norm(np.diff(route, axis=0), axis=1)
    along = np.concatenate([[0.0], np.cumsum(steps)])
    if distance >= along[-1]:
        return route[-1]
    i = int(np.searchsorted(along, distance, side="right")) - 1
    share = (distance - along[i]) / steps[i] if steps[i] > 0 else 0.0
    return route[i] + share * (route[i + 1] - route[i])


def follow_step(route_m: np.ndarray | None, cfg: NavConfig = NavConfig(),
                fcfg: FollowConfig = FollowConfig()) -> tuple[tuple[float, float], bool]:
    """One step along the route. Returns ((speed m/s, turn rate rad/s, left positive), arrived).

    route_m: (N, 2) points in metres in the chair's frame, from near the chair to the stop point, or None."""
    if route_m is None:
        return (0.0, 0.0), False
    points = np.asarray(route_m, dtype=float).reshape(-1, 2)
    if len(points) == 0 or not np.isfinite(points).all():
        return (0.0, 0.0), False
    route = np.vstack([[0.0, 0.0], points])  # the chair itself, then the unseen strip, then the visible route
    remaining = float(np.linalg.norm(np.diff(route, axis=0), axis=1).sum())
    if remaining <= fcfg.stop_short_m:
        return (0.0, 0.0), True
    aim = _lookahead_point(route, min(fcfg.lookahead_m, remaining))
    reach = float(np.hypot(*aim))
    if reach < 1e-6:
        return (0.0, 0.0), False
    bearing = math.atan2(aim[1], aim[0])  # angle to the look-ahead point: positive = it is to the left
    limit = math.radians(fcfg.turn_in_place_deg)
    if abs(bearing) > limit:  # far off to the side or behind: turn on the spot toward it, never reverse
        return (0.0, math.copysign(fcfg.turn_rate_frac * cfg.max_yaw_rate, bearing)), False
    # Pure pursuit: the circle through the chair and the look-ahead point has curvature 2*sin(bearing)/reach.
    curvature = 2.0 * math.sin(bearing) / reach
    speed = cfg.max_speed * (1.0 - 0.6 * abs(bearing) / limit)  # ease off the more the route bends away
    to_stop = remaining - fcfg.stop_short_m
    if to_stop < fcfg.slow_down_m:  # coming up to the stop point: slow down in a straight line
        speed = min(speed, max(fcfg.min_speed, cfg.max_speed * to_stop / fcfg.slow_down_m))
    turn = speed * curvature
    if abs(turn) > cfg.max_yaw_rate:  # cannot turn that fast: slow down so the chair still follows the same circle
        turn = math.copysign(cfg.max_yaw_rate, turn)
        speed = abs(turn / curvature)
    return (speed, turn), False
