"""Route follower (control/follow.py): pure pursuit on a route in the chair's frame. No camera, no hardware."""

import math

import numpy as np
import pytest

from control.follow import FollowConfig, follow_step
from control.navigation import NavConfig, to_wheels

CFG, FCFG = NavConfig(), FollowConfig()


def test_no_route_or_a_broken_route_means_stop_without_claiming_arrival():
    for route in (None, np.zeros((0, 2)), np.array([[1.0, float("nan")]]), np.array([[float("inf"), 0.0]])):
        assert follow_step(route) == ((0.0, 0.0), False)


def test_straight_route_drives_straight_at_cruise_speed():
    (speed, turn), arrived = follow_step(np.array([[1.7, 0.0], [4.0, 0.0]]))
    assert not arrived and speed == pytest.approx(CFG.max_speed) and turn == pytest.approx(0.0)


def test_route_bending_left_turns_left_and_the_right_wheel_runs_faster():
    (speed, turn), _ = follow_step(np.array([[1.0, 0.3], [2.0, 1.0]]))
    left, right = to_wheels(speed, turn, CFG)
    assert speed > 0 and turn > 0 and right > left
    (_, mirrored), _ = follow_step(np.array([[1.0, -0.3], [2.0, -1.0]]))
    assert mirrored == pytest.approx(-turn)  # the same route on the other side turns the other way just as hard


def test_route_far_off_to_the_side_turns_on_the_spot_first_and_never_reverses():
    (speed, turn), arrived = follow_step(np.array([[0.1, 1.0], [0.1, 2.5]]))
    assert not arrived and speed == 0.0 and turn > 0
    (speed, turn), _ = follow_step(np.array([[-1.0, -0.2], [-2.5, -0.2]]))  # the route is behind the chair
    assert speed == 0.0 and turn < 0


def test_arrives_when_less_than_the_stop_distance_of_route_is_left():
    assert follow_step(np.array([[0.2, 0.0], [FCFG.stop_short_m - 0.05, 0.0]])) == ((0.0, 0.0), True)
    (speed, _), arrived = follow_step(np.array([[0.2, 0.0], [FCFG.stop_short_m + 0.3, 0.0]]))
    assert not arrived and FCFG.min_speed <= speed < CFG.max_speed  # close to the stop point: slowed, not stopped


def test_speed_and_turn_rate_never_exceed_the_planner_limits_and_the_input_is_left_alone():
    rng = np.random.default_rng(0)
    for _ in range(300):
        route = np.cumsum(rng.uniform(-0.6, 0.9, (5, 2)), axis=0) + [0.5, 0.0]
        before = route.copy()
        (speed, turn), _ = follow_step(route)
        assert 0.0 <= speed <= CFG.max_speed + 1e-9 and abs(turn) <= CFG.max_yaw_rate + 1e-9
        assert np.array_equal(route, before)


def in_chair_frame(points: np.ndarray, pose: tuple[float, float, float]) -> np.ndarray:
    """World points -> the chair's frame (chair at the origin, facing +x)."""
    x, y, heading = pose
    shifted = points - [x, y]
    cos, sin = math.cos(-heading), math.sin(-heading)
    return shifted @ np.array([[cos, sin], [-sin, cos]])


def route_ahead(world: np.ndarray, pose: tuple[float, float, float]) -> np.ndarray:
    """What a fresh plan would give: the route from the point nearest the chair onward, in the chair's frame."""
    dense = np.concatenate([np.linspace(a, b, 40, endpoint=False) for a, b in zip(world, world[1:])] + [world[-1:]])
    nearest = int(np.argmin(np.linalg.norm(dense - pose[:2], axis=1)))
    return in_chair_frame(dense[nearest + 1:], pose)


def test_closed_loop_the_chair_stays_on_a_route_with_a_detour_and_stops_short_of_its_end():
    """Ideal chair, re-planned every step (as the camera does): drive a route that swings 0.8 m left around
    something and comes back. It must stay near the route the whole way and stop near its end."""
    world = np.array([[0.0, 0.0], [1.0, 0.0], [2.0, 0.8], [3.0, 0.8], [4.0, 0.0], [5.0, 0.0]])
    dense = np.concatenate([np.linspace(a, b, 200) for a, b in zip(world, world[1:])])
    pose, dt, worst, arrived = (0.0, 0.0, 0.0), 0.05, 0.0, False
    for _ in range(1200):  # at most 60 s
        (speed, turn), arrived = follow_step(route_ahead(world, pose))
        if arrived:
            break
        x, y, heading = pose
        pose = (x + speed * math.cos(heading) * dt, y + speed * math.sin(heading) * dt, heading + turn * dt)
        worst = max(worst, float(np.min(np.linalg.norm(dense - pose[:2], axis=1))))
    left_to_go = math.dist(pose[:2], world[-1])
    assert arrived
    assert worst < 0.10  # stays inside the margin the route planner reserves for following error
    assert 0.3 < left_to_go <= FCFG.stop_short_m + 0.05  # stopped short of the end, not on top of it
