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

# "Too close to measure" (used only when the caller passes the frame height). Distance comes from the HEIGHT of the
# object's box (vision/detect_track.py: distance = typical height * focal length / box height), so the camera
# stops seeing an object get closer in two cases, and in both the planner must stop instead of trusting the number:
FULL_FRAME_FRACTION = 0.9  # 1) the box fills the picture top to bottom. A box cannot be taller than the frame, so
#                            the reading has a floor (chair 0.87 m, person 1.63 m at 1920x1080) above ARRIVE_M.
#                            reading / smallest possible reading = frame height / box height, for every label, so
#                            "box at least 90% of the frame" means "reading within 11% of the smallest possible".
FRAME_EDGE_FRACTION = 0.02  # 2) the box runs off the bottom of the picture (its foot is out of view). Detector
#                             boxes end a pixel or two short of the edge, so within 2% of the frame height counts.
CUT_OFF_ARRIVE_M = 2.5  # A cut-off box reading within this = arrived. A cut-off box is SHORTER than the whole
#                         object would be, so its reading is too far, never too near (chairs standing 1.40 m away
#                         read 1.7 m, live check Sat Nov 14): reading under 2.5 m means truly nearer than 2.5 m.
#                         Why 2.5: the floor leaves the bottom of the picture about 1.1 to 1.9 m ahead of a camera
#                         1 m up (tilted 15 deg down .. level), so an object the chair drives up to is first cut off
#                         inside that range, at a moment when it still reads right.
#                         A cut-off box reading FARTHER than this is not arrived (a small box that merely ends on
#                         the bottom edge at 3 m: camera tipped up, detector's box wandering) but it is not driven
#                         at either: the reading is known to be too far by an unknown amount (a chair 0.5 m away
#                         seen from above reads 2.8 m), and an untrustworthy reading means STOP (AGENTS.md rule 1).


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


def _box_at_frame_limit(target, frame_h: int) -> tuple[bool, bool]:
    """(box fills the picture top to bottom?, box runs off the bottom edge?) - see the constants above."""
    _, y1, _, y2 = target.bbox
    fills_frame = (y2 - y1) >= FULL_FRAME_FRACTION * frame_h
    cut_off_at_bottom = y2 >= (1 - FRAME_EDGE_FRACTION) * frame_h  # y grows downward: y2 is the box's lower edge
    return fills_frame, cut_off_at_bottom


def nav_step(nav: NavState, target, others: Sequence, frame_w: int, hfov_deg: float, distance_cm: int | None,
             cfg: NavConfig = NavConfig(), *, frame_h: int | None = None,
             ) -> tuple[NavState, tuple[int, int], bool]:
    """One planner step toward `target`. Returns (new state, (left, right) firmware speeds, arrived?).
    frame_h: height of the camera frame in pixels. When given, a target the camera can no longer measure getting
    closer (box fills the frame, or runs off its bottom edge) counts as arrived; see FULL_FRAME_FRACTION and
    CUT_OFF_ARRIVE_M. Without it only the distance reading decides, exactly as before."""
    if target.distance_m is None:
        return NavState(), (0, 0), False  # no distance estimate: do not guess, do not move
    if frame_h is not None:
        if frame_h <= 0:
            return NavState(), (0, 0), False  # a frame cannot be 0 pixels high: bad input, do not move
        fills_frame, cut_off_at_bottom = _box_at_frame_limit(target, frame_h)
        if fills_frame or (cut_off_at_bottom and target.distance_m <= CUT_OFF_ARRIVE_M):
            return NavState(), (0, 0), True  # as near as the camera can tell: stop here and say so
        if cut_off_at_bottom:
            return NavState(), (0, 0), False  # reads far, but the reading cannot be trusted: do not move
    x1, _, x2, _ = target.bbox
    goal = goal_from_target(_offset((x1 + x2) / 2, frame_w), target.distance_m, hfov_deg)
    obstacles = obstacles_from_tracks(others, target.id, frame_w, hfov_deg)
    if distance_cm is not None and distance_cm > 0:
        obstacles = np.vstack([obstacles, obstacles_from_ultrasonic([(ULTRASONIC_ANGLE_DEG, distance_cm / 100)])])
    v, w = dwa_control(nav.v, nav.w, goal, obstacles, cfg)
    arrived = float(np.hypot(*goal)) < ARRIVE_M  # same rule the planner uses to return (0, 0)
    return NavState(v, w), to_wheels(v, w, cfg), arrived
