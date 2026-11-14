"""Drive-to-object: camera obstacles + one planner step per frame (control/goto.py)."""

import math

import numpy as np
import pytest

from control.goto import NavState, nav_step, obstacles_from_tracks
from control.navigation import ARRIVE_M
from vision.detect_track import Track

W, HFOV = 1920, 85.5


def track(tid, x_center, width=200, distance=2.0, label="chair"):
    return Track(id=tid, label=label, conf=0.9, bbox=(x_center - width / 2, 300, x_center + width / 2, 700),
                 distance_m=distance)


def test_other_objects_become_obstacles_with_their_width_target_excluded():
    target, chair = track(1, 960), track(2, 1500, width=300, distance=1.5)
    pts = obstacles_from_tracks([target, chair], exclude_id=1, frame_w=W, hfov_deg=HFOV)
    assert pts.shape == (3, 2)  # left edge, centre, right edge of the chair; nothing for the target
    assert all(p[1] < 0 for p in pts)  # chair is right of centre -> negative y (right side)
    assert all(math.hypot(*p) == pytest.approx(1.5, abs=0.01) for p in pts)


def test_objects_without_a_distance_are_skipped():
    no_dist = Track(id=3, label="person", conf=0.9, bbox=(0, 0, 10, 10), distance_m=None)
    assert obstacles_from_tracks([no_dist], exclude_id=1, frame_w=W, hfov_deg=HFOV).shape == (0, 2)


def test_centred_target_drives_straight():
    nav, (left, right), arrived = nav_step(NavState(), track(1, 960, distance=3.0), [], W, HFOV, distance_cm=None)
    assert not arrived and left > 0 and right > 0 and abs(left - right) <= 2


def test_target_on_the_right_turns_right():
    nav = NavState()
    for _ in range(5):  # let the planner ramp up (it limits acceleration)
        nav, (left, right), _ = nav_step(nav, track(1, 1700, distance=2.5), [], W, HFOV, distance_cm=None)
    assert left > right  # left wheel faster = turning right


def test_arrived_stops_and_says_so():
    nav, wheels, arrived = nav_step(NavState(v=0.3), track(1, 960, distance=ARRIVE_M - 0.1), [], W, HFOV, None)
    assert arrived and wheels == (0, 0)


def test_ultrasonic_obstacle_ahead_prevents_driving_into_it():
    nav = NavState()
    speeds = []
    for _ in range(10):
        nav, (left, right), _ = nav_step(nav, track(1, 960, distance=3.0), [], W, HFOV, distance_cm=40)
        speeds.append((left + right) / 2)
    assert max(speeds) <= 0  # something 40 cm ahead: never drives forward into it


def test_nav_state_is_immutable():
    state = NavState()
    nav_step(state, track(1, 960, distance=3.0), [], W, HFOV, None)
    assert (state.v, state.w) == (0.0, 0.0)
