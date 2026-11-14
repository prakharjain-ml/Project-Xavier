"""Go-to-object navigation (control/navigation.py): goal from the camera, obstacles from ultrasonics,
Dynamic Window Approach picks speed + turn. Includes closed-loop simulations of the chair driving."""

import math

import numpy as np
import pytest

from control.navigation import (
    ARRIVE_M,
    WHEEL_DEAD_BAND,
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


# --- Motor dead band (audit finding 8): the board treats |speed| < 50 as stop -----------------------------------


def planner_speed_sweep():
    """Every (speed, turn rate) the planner is allowed to pick, on a fine grid."""
    return [(float(v), float(w)) for v in np.arange(0.0, CFG.max_speed + 1e-9, 0.01)
            for w in np.arange(-CFG.max_yaw_rate, CFG.max_yaw_rate + 1e-9, math.radians(1.0))]


def old_wheels(v, w):
    """The conversion before the dead-band fix, unrounded (for comparison)."""
    half = CFG.track_width / 2
    top = CFG.max_speed + CFG.max_yaw_rate * half
    return (v - w * half) / top * MAX_SPEED, (v + w * half) / top * MAX_SPEED


def test_no_wheel_command_is_ever_inside_the_dead_band_across_the_planner_range():
    for v, w in planner_speed_sweep():
        assert all(s == 0 or abs(s) >= WHEEL_DEAD_BAND for s in to_wheels(v, w, CFG)), (v, w)


def test_any_motion_the_planner_intends_reaches_at_least_one_wheel():
    for v, w in planner_speed_sweep():
        intended = max(abs(s) for s in old_wheels(v, w)) >= 0.5  # used to round to something other than (0, 0)
        assert (to_wheels(v, w, CFG) != (0, 0)) == intended, (v, w)


def test_turn_in_place_is_lifted_to_the_slowest_spin_the_board_acts_on():
    assert to_wheels(0.0, CFG.max_yaw_rate, CFG) == (-WHEEL_DEAD_BAND, WHEEL_DEAD_BAND)  # was (-49, 49)
    assert to_wheels(0.0, -math.radians(6.0), CFG) == (WHEEL_DEAD_BAND, -WHEEL_DEAD_BAND)  # was (7, -7)


def test_slow_forward_is_lifted_to_the_slowest_speed_the_board_acts_on():
    assert to_wheels(0.02, 0.0, CFG) == (WHEEL_DEAD_BAND, WHEEL_DEAD_BAND)  # was (5, 5)
    assert to_wheels(0.19, 0.0, CFG) == (WHEEL_DEAD_BAND, WHEEL_DEAD_BAND)  # was (48, 48)


def test_stop_stays_stop():
    assert to_wheels(0.0, 0.0, CFG) == (0, 0)
    assert to_wheels(1e-9, 1e-9, CFG) == (0, 0)  # rounding noise is not a request to move


def test_dead_band_fix_does_not_raise_the_top_speed_or_touch_faster_commands():
    assert to_wheels(CFG.max_speed, 0.0, CFG) == (101, 101)
    for v, w in planner_speed_sweep():
        old, new = old_wheels(v, w), to_wheels(v, w, CFG)
        assert max(abs(s) for s in new) <= max(WHEEL_DEAD_BAND, round(max(abs(s) for s in old))), (v, w)
        if min(abs(s) for s in old) >= WHEEL_DEAD_BAND:
            assert new == (round(old[0]), round(old[1])), (v, w)  # both wheels already outside: unchanged


def test_dead_band_fix_never_reverses_a_wheel_or_the_turn_direction():
    for v, w in planner_speed_sweep():
        old, (left, right) = old_wheels(v, w), to_wheels(v, w, CFG)
        assert left * old[0] >= 0 and right * old[1] >= 0, (v, w)
        assert (right - left) * w >= 0, (v, w)  # right wheel faster = turning left = positive w


def test_planner_driven_at_a_wall_never_commands_a_speed_inside_the_dead_band():
    # Arrange: solid wall 1 m ahead: the planner creeps up, stops, then turns on the spot (the slow commands)
    wall = np.array([(1.0, y) for y in np.arange(-2.0, 2.01, 0.1)])
    state, commands = np.zeros(5), []

    # Act
    for _ in range(150):
        local = np.array([to_local(state, o) for o in wall])
        v, w = dwa_control(state[3], state[4], to_local(state, (4.0, 0.0)), local, CFG)
        commands.append(to_wheels(v, w, CFG))
        state = motion(state, (v, w), CFG.dt)

    # Assert
    assert all(s == 0 or abs(s) >= WHEEL_DEAD_BAND for pair in commands for s in pair)
    assert any(left * right < 0 for left, right in commands)  # it did ask for a turn on the spot


def test_slower_wheel_of_a_turn_moves_to_the_nearer_of_stop_and_dead_band():
    # Arrange: turning left around a left wheel that is almost still (it wanted +3, then -3)
    slow_forward, slow_backward = to_wheels(0.12, 0.4, CFG), to_wheels(0.10, 0.4, CFG)

    # Assert: it stays stopped instead of jumping between +50 and -50; a wheel nearer the dead band is lifted
    assert slow_forward == (0, 58) and slow_backward == (0, 53)
    assert to_wheels(0.3, 0.6, CFG) == (WHEEL_DEAD_BAND, 118)  # was (34, 118)
    for v, w in planner_speed_sweep():
        old, new = old_wheels(v, w), to_wheels(v, w, CFG)
        if max(abs(s) for s in old) >= WHEEL_DEAD_BAND:  # pair not rescaled: no wheel moved by more than half
            assert all(abs(n - o) <= WHEEL_DEAD_BAND / 2 + 0.5 for n, o in zip(new, old)), (v, w)
