"""Shortest safe path on a floor grid (control/astar.py)."""

import math

import numpy as np

from control.astar import astar_path, path_length


def test_free_floor_gives_a_straight_path():
    path = astar_path((3.0, 0.0), np.zeros((0, 2)))
    assert path is not None and len(path) == 2  # smoothed to one straight run
    assert path[0] == (0.0, 0.0) and math.dist(path[-1], (3.0, 0.0)) < 0.15


def test_path_goes_around_an_obstacle_with_clearance():
    obstacle = np.array([[1.5, 0.0]])
    path = astar_path((3.0, 0.0), obstacle, robot_radius=0.45)
    assert path is not None
    dense = np.concatenate([np.linspace(a, b, 20) for a, b in zip(path, path[1:])])
    assert min(math.dist(p, obstacle[0]) for p in dense) >= 0.45 - 0.08  # never cuts through the safety zone
    assert path_length(path) > 3.0  # longer than straight because it detours


def test_wall_with_no_gap_returns_none():
    wall = np.array([[1.5, y] for y in np.arange(-2.6, 2.61, 0.1)])
    assert astar_path((3.0, 0.0), wall) is None


def test_goal_beyond_the_map_is_clamped_not_dropped():
    path = astar_path((9.0, 0.0), np.zeros((0, 2)))
    assert path is not None and path[-1][0] <= 5.0
