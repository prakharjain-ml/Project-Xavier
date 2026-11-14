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
    if blocked[goal]:
        return None
    came_from, cost, frontier = {start: None}, {start: 0.0}, [(0.0, start)]
    while frontier:
        _, current = heapq.heappop(frontier)
        if current == goal:
            break
        for dx, dy in _NEIGHBOURS:
            nxt = (current[0] + dx, current[1] + dy)
            if not (0 <= nxt[0] < nx and 0 <= nxt[1] < ny) or blocked[nxt]:
                continue
            new_cost = cost[current] + math.hypot(dx, dy) * CELL
            if new_cost < cost.get(nxt, math.inf):
                cost[nxt], came_from[nxt] = new_cost, current
                heapq.heappush(frontier, (new_cost + math.dist(nxt, goal) * CELL, nxt))
    if goal not in came_from:
        return None
    cells, node = [], goal
    while node is not None:
        cells.append(node)
        node = came_from[node]
    points = [(float(xs[i]), float(ys[j])) for i, j in reversed(cells)]
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
