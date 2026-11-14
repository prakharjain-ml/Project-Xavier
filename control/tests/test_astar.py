"""Shortest safe path on a floor grid (control/astar.py)."""

import math

import numpy as np

from control.astar import astar_path, grid_search, path_length


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


# ---------------------------------------------------------------- grid_search (shared with vision/floor_route.py)

def test_grid_search_on_an_empty_grid_walks_straight_to_the_goal():
    blocked = np.zeros((5, 9), dtype=bool)

    cells = grid_search(blocked, (2, 0), (2, 8))

    assert cells == [(2, j) for j in range(9)]


def test_grid_search_goes_around_a_wall_and_never_steps_on_a_blocked_cell():
    blocked = np.zeros((7, 7), dtype=bool)
    blocked[0:6, 3] = True  # a wall with one gap, at the bottom row

    cells = grid_search(blocked, (0, 0), (0, 6))

    assert cells[0] == (0, 0) and cells[-1] == (0, 6) and (6, 3) in cells
    assert not any(blocked[cell] for cell in cells)
    assert all(max(abs(a[0] - b[0]), abs(a[1] - b[1])) == 1 for a, b in zip(cells, cells[1:]))  # 8-connected


def test_grid_search_returns_none_when_the_goal_is_walled_off_or_blocked():
    walled = np.zeros((5, 5), dtype=bool)
    walled[:, 2] = True
    goal_blocked = np.zeros((5, 5), dtype=bool)
    goal_blocked[4, 4] = True

    assert grid_search(walled, (0, 0), (0, 4)) is None
    assert grid_search(goal_blocked, (0, 0), (4, 4)) is None


def test_grid_search_extra_cost_pushes_the_path_off_expensive_cells():
    blocked = np.zeros((5, 9), dtype=bool)
    extra = np.zeros((5, 9))
    extra[2, 1:8] = 10.0  # the straight row is free but costly to enter

    cells = grid_search(blocked, (2, 0), (2, 8), extra_cost=extra)

    assert not any(cell[0] == 2 for cell in cells[1:-1])


def test_grid_search_when_start_is_the_goal_returns_that_one_cell():
    assert grid_search(np.zeros((3, 3), dtype=bool), (1, 1), (1, 1)) == [(1, 1)]


def test_grid_search_does_not_modify_its_inputs():
    blocked = np.zeros((5, 5), dtype=bool)
    blocked[2, 1:4] = True
    extra = np.full((5, 5), 0.5)
    blocked_before, extra_before = blocked.copy(), extra.copy()

    grid_search(blocked, (0, 0), (4, 4), extra_cost=extra)

    assert np.array_equal(blocked, blocked_before) and np.array_equal(extra, extra_before)
