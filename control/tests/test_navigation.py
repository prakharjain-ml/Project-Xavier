"""Go-to-object navigation (control/navigation.py): goal from the camera, obstacles from ultrasonics,
Dynamic Window Approach picks speed + turn. Includes closed-loop simulations of the chair driving."""

import math

import numpy as np
import pytest

from control.navigation import (
    ARRIVE_M,
    NavConfig,
    dwa_control,
    goal_from_target,
    motion,
    obstacles_from_ultrasonic,
    to_wheels,
)
from shared.protocol import MAX_SPEED

CFG = NavConfig()


def simulate(goal, obstacles, steps=300):
    """Drive the simulated chair with the planner; return its path (x, y) and final state."""
    state = np.zeros(5)  # x, y, heading, speed, turn rate
    path = [state[:2].copy()]
    for _ in range(steps):
        local_goal, local_obs = to_local(state, goal), [to_local(state, o) for o in obstacles]
        v, w = dwa_control(state[3], state[4], local_goal, np.array(local_obs).reshape(-1, 2), CFG)
        state = motion(state, (v, w), CFG.dt)
        path.append(state[:2].copy())
        if math.dist(state[:2], goal) < ARRIVE_M + 0.05:
            break
    return np.array(path), state


def to_local(state, point):
    """World point -> chair frame (x forward, y left)."""
    dx, dy = point[0] - state[0], point[1] - state[1]
    c, s = math.cos(-state[2]), math.sin(-state[2])
    return (c * dx - s * dy, s * dx + c * dy)


def test_goal_from_camera_target():
    x, y = goal_from_target(steer_offset=0.0, distance_m=3.0, hfov_deg=85.5)
    assert (x, y) == pytest.approx((3.0, 0.0))
    _, y_right = goal_from_target(steer_offset=+0.5, distance_m=3.0, hfov_deg=85.5)
    assert y_right < 0  # object right of centre -> goal on the chair's right (negative y)


def test_ultrasonic_readings_become_obstacle_points_and_invalid_ones_are_dropped():
    pts = obstacles_from_ultrasonic([(0.0, 1.0), (30.0, 2.0), (-30.0, None), (0.0, -1), (0.0, 9.0)])
    assert pts.shape == (2, 2)
    assert pts[0] == pytest.approx((1.0, 0.0))
    assert pts[1][1] > 0  # +30 deg sensor (left side) -> positive y


def test_free_path_drives_straight_at_the_goal():
    v, w = dwa_control(0.0, 0.0, (3.0, 0.0), np.empty((0, 2)), CFG)
    assert v > 0 and abs(w) < 0.15


def test_goal_on_the_left_turns_left():
    v, w = dwa_control(0.0, 0.0, (1.5, 1.5), np.empty((0, 2)), CFG)
    assert w > 0


def test_arrived_means_stop():
    assert dwa_control(0.3, 0.1, (ARRIVE_M - 0.1, 0.0), np.empty((0, 2)), CFG) == (0.0, 0.0)


def test_simulated_chair_reaches_goal_around_an_obstacle_without_touching_it():
    goal, obstacle = (4.0, 0.0), (2.0, 0.05)  # something right in the way
    path, final = simulate(goal, [obstacle])
    assert math.dist(final[:2], goal) < ARRIVE_M + 0.1  # got there
    closest = min(math.dist(p, obstacle) for p in path)
    assert closest > CFG.robot_radius + 0.1  # passes with comfortable room, not skimming the safety bubble


def test_simulated_chair_reaches_a_goal_to_the_right():
    path, final = simulate(goal_from_target(0.6, 3.0, 85.5), [])
    assert math.dist(final[:2], goal_from_target(0.6, 3.0, 85.5)) < ARRIVE_M + 0.1


def test_blocked_with_no_way_through_never_drives_into_the_wall():
    wall = [(1.0, y) for y in np.arange(-2.0, 2.01, 0.1)]  # solid wall 1 m ahead
    path, final = simulate((4.0, 0.0), wall, steps=150)
    assert all(p[0] < 1.0 - CFG.robot_radius + 0.05 for p in path)


def test_wheel_speeds_are_differential_and_capped():
    left, right = to_wheels(0.3, 0.0, CFG)
    assert left == right > 0
    left, right = to_wheels(0.0, 0.6, CFG)
    assert left < 0 < right  # turning left in place: left wheel back, right wheel forward
    assert all(abs(s) <= MAX_SPEED for s in to_wheels(10.0, 10.0, CFG))
