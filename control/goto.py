"""Drive to the confirmed object: one planner step per camera frame.

Obstacles come from two places: every object the camera sees OTHER than the target (direction from its position in
the frame, distance from its box size, with its left/right edges so the planner knows its width), and the forward
ultrasonic reading from the ESP32. The Dynamic Window Approach (control/navigation.py) then picks speed + turn.

This only proposes wheel speeds. The safety state machine still decides whether the chair may move at all (hold
to move, obstacle block, stop by default), and the ESP32 still stops on its own.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from control.navigation import ARRIVE_M, NavConfig, dwa_control, goal_from_target, obstacles_from_ultrasonic, to_wheels

ULTRASONIC_ANGLE_DEG = 0.0  # the single HC-SR04 points straight ahead


@dataclass(frozen=True)
class NavState:
    v: float = 0.0  # current forward speed, m/s (the planner limits how fast it may change)
    w: float = 0.0  # current turn rate, rad/s


def _offset(x_px: float, frame_w: int) -> float:
    return (x_px - frame_w / 2) / (frame_w / 2)  # -1 left edge .. +1 right edge


def obstacles_from_tracks(tracks: Sequence, exclude_id: int | None, frame_w: int, hfov_deg: float) -> np.ndarray:
    """Every tracked object except the target -> obstacle points (left edge, centre, right edge) in metres."""
    points = []
    for t in tracks:
        if t.id == exclude_id or t.distance_m is None:
            continue
        x1, _, x2, _ = t.bbox
        for x in (x1, (x1 + x2) / 2, x2):
            points.append(goal_from_target(_offset(x, frame_w), t.distance_m, hfov_deg))
    return np.array(points, dtype=float).reshape(-1, 2)


def nav_step(nav: NavState, target, others: Sequence, frame_w: int, hfov_deg: float, distance_cm: int | None,
             cfg: NavConfig = NavConfig()) -> tuple[NavState, tuple[int, int], bool]:
    """One planner step toward `target`. Returns (new state, (left, right) firmware speeds, arrived?)."""
    if target.distance_m is None:
        return NavState(), (0, 0), False  # no distance estimate: do not guess, do not move
    x1, _, x2, _ = target.bbox
    goal = goal_from_target(_offset((x1 + x2) / 2, frame_w), target.distance_m, hfov_deg)
    obstacles = obstacles_from_tracks(others, target.id, frame_w, hfov_deg)
    if distance_cm is not None and distance_cm > 0:
        obstacles = np.vstack([obstacles, obstacles_from_ultrasonic([(ULTRASONIC_ANGLE_DEG, distance_cm / 100)])])
    v, w = dwa_control(nav.v, nav.w, goal, obstacles, cfg)
    arrived = float(np.hypot(*goal)) < ARRIVE_M  # same rule the planner uses to return (0, 0)
    return NavState(v, w), to_wheels(v, w, cfg), arrived
