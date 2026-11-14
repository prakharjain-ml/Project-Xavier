"""Shortest safe path on the floor (A*), for showing the route the chair would take.

The floor in front of the chair becomes a grid of CELL x CELL squares. Every square within robot_radius of an
obstacle is blocked (that "grows" each obstacle by the chair's size, so the path can treat the chair as a point).
A* then finds the shortest route over free squares, and the result is smoothed into straight runs wherever the
straight line stays clear. The Dynamic Window planner (control/navigation.py) still drives the motors; this path is
the route it is heading along, drawn on the floor for the rider and the judges.
Frame: chair at (0, 0), x forward, y left, metres.
"""

from __future__ import annotations

import heapq
import math

import numpy as np

CELL = 0.1  # m
X_MIN, X_MAX, Y_MIN, Y_MAX = -0.5, 5.0, -2.5, 2.5  # the patch of floor we plan over
_NEIGHBOURS = [(dx, dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1) if (dx, dy) != (0, 0)]


def _clamp_goal(goal) -> tuple[float, float]:
    """Pull a goal that lies beyond the map back along its own direction, so the path still heads the right way."""
    gx, gy = goal
    scale = 1.0
    if gx > X_MAX - CELL:
        scale = min(scale, (X_MAX - CELL) / gx)
    if abs(gy) > Y_MAX - CELL:
        scale = min(scale, (Y_MAX - CELL) / abs(gy))
    return gx * scale, gy * scale


def grid_search(blocked: np.ndarray, start: tuple[int, int], goal: tuple[int, int], cell_size: float = 1.0,
                extra_cost: np.ndarray | None = None) -> list[tuple[int, int]] | None:
    """A* over a 2-D grid: the cheapest 8-connected chain of free cells from `start` to `goal`, or None.

    `blocked[i, j]` is True where a cell may not be entered. A step costs its length (cell_size, or cell_size
    times sqrt(2) on a diagonal) plus `extra_cost` of the cell it enters, if given (must be >= 0). Both planners
    use this: the metric one below, and the image one in vision/floor_route.py. Inputs are not modified.
    """
    n_i, n_j = blocked.shape
    width = n_j + 2  # one ring of blocked cells is added around the grid, so the loop needs no edge checks
    padded = np.ones((n_i + 2, width), dtype=bool)
    padded[1:-1, 1:-1] = blocked
    # Plain Python lists indexed by one number (row * width + column) are much faster to read than numpy cells.
    is_blocked = padded.ravel().tolist()
    extra = np.zeros(padded.shape)
    if extra_cost is not None:
        extra[1:-1, 1:-1] = extra_cost
    extra = extra.ravel().tolist()
    moves = [(di * width + dj, di, dj, math.hypot(di, dj) * cell_size) for di, dj in _NEIGHBOURS]
    start_n, goal_n = (start[0] + 1) * width + start[1] + 1, (goal[0] + 1) * width + goal[1] + 1
    if is_blocked[goal_n]:
        return None
    goal_i, goal_j = goal[0] + 1, goal[1] + 1
    cost = [math.inf] * len(is_blocked)  # cheapest known cost to reach each cell
    came_from = {start_n: None}
    cost[start_n] = 0.0
    done = [False] * len(is_blocked)  # cells whose neighbours have already been looked at
    frontier = [(0.0, start_n)]  # (cost so far + straight-line guess of the rest, cell); smallest pops first
    while frontier:
        _, current = heapq.heappop(frontier)
        if current == goal_n:
            break
        if done[current]:  # an older, more expensive entry for a cell that was already handled: skip it
            continue
        done[current] = True
        i, j = divmod(current, width)
        cost_here = cost[current]
        for offset, di, dj, step in moves:
            nxt = current + offset
            if is_blocked[nxt]:
                continue
            new_cost = cost_here + step + extra[nxt]
            if new_cost < cost[nxt]:
                cost[nxt], came_from[nxt] = new_cost, current
                # The guess never overestimates (a straight line is the shortest way), so the first time the
                # goal pops its path is the cheapest one.
                guess = math.hypot(i + di - goal_i, j + dj - goal_j) * cell_size
                heapq.heappush(frontier, (new_cost + guess, nxt))
    return _walk_back(came_from, goal_n, width) if goal_n in came_from else None


def _walk_back(came_from: dict[int, int | None], goal_n: int, width: int) -> list[tuple[int, int]]:
    """Follow the "came from" links from the goal back to the start; return the cells in start-to-goal order."""
    cells, node = [], goal_n
    while node is not None:
        cells.append((node // width - 1, node % width - 1))  # back from padded numbering to (i, j)
        node = came_from[node]
    return cells[::-1]


def astar_path(goal, obstacles: np.ndarray, robot_radius: float = 0.45) -> list[tuple[float, float]] | None:
    """Shortest path from the chair to `goal` that keeps robot_radius from every obstacle, or None if blocked."""
    nx, ny = int(round((X_MAX - X_MIN) / CELL)) + 1, int(round((Y_MAX - Y_MIN) / CELL)) + 1
    xs, ys = X_MIN + np.arange(nx) * CELL, Y_MIN + np.arange(ny) * CELL
    gx_grid, gy_grid = np.meshgrid(xs, ys, indexing="ij")
    blocked = np.zeros((nx, ny), dtype=bool)
    for ox, oy in np.asarray(obstacles, dtype=float).reshape(-1, 2):
        blocked |= np.hypot(gx_grid - ox, gy_grid - oy) <= robot_radius

    def cell(p):
        return int(round((p[0] - X_MIN) / CELL)), int(round((p[1] - Y_MIN) / CELL))

    start, goal = cell((0.0, 0.0)), cell(_clamp_goal(goal))
    blocked[start] = False  # the chair is where it is
    cells = grid_search(blocked, start, goal, cell_size=CELL)
    if cells is None:
        return None
    points = [(float(xs[i]), float(ys[j])) for i, j in cells]
    points[0] = (0.0, 0.0)
    return _smooth(points, blocked, cell)


def _clear(a, b, blocked, cell) -> bool:
    steps = max(2, int(math.dist(a, b) / (CELL / 2)))
    return not any(blocked[cell((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))]
                   for t in np.linspace(0.0, 1.0, steps))


def _smooth(points, blocked, cell):
    """Replace zig-zag grid steps with straight runs wherever the straight line stays clear (string pulling)."""
    smoothed, i = [points[0]], 0
    while i < len(points) - 1:
        j = len(points) - 1
        while j > i + 1 and not _clear(points[i], points[j], blocked, cell):
            j -= 1
        smoothed.append(points[j])
        i = j
    return smoothed


def path_length(path) -> float:
    return float(sum(math.dist(a, b) for a, b in zip(path, path[1:])))
