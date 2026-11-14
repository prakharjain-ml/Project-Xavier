"""Route preview planned directly in the camera image, so it provably stays on visible floor.

The old preview planned in guessed metric coordinates and drew the route across furniture. Here everything is
a pixel mask of the camera frame (x right, y down), and the route is found and then re-checked on those masks:

  C1  every point of the route is on free floor (floor minus objects minus no-go zones);
  C2  the chair fits: free floor at least half a chair-width on both sides (the target itself is exempt);
  C3  the route starts at the bottom edge (the chair) and ends on the floor next to the target, not on it;
  C4  if no route passes C1 to C3, `plan_route` returns None. It never returns a best guess;
  C5  detector outlines always beat Gemini: `free_floor` removes objects from whatever floor it is given.

How the planner works, in order:
  1. clearance: for every pixel, the distance to the nearest pixel that is neither free floor nor target;
  2. the chair's half-width in pixels grows with the image row (near things look bigger), so a pixel is
     drivable when its clearance is at least the half-width of its row;
  3. A* (control/astar.py) on a coarse grid, one cell per CELL_PX pixels, with a small extra cost near
     obstacles so the route prefers the middle of a corridor;
  4. smoothing (straight shortcuts, then rounded corners), each piece accepted only if it is still clear;
  5. `route_violations` re-checks the final points at full resolution. A route that fails is not returned.

Pure functions: numpy and cv2 only, no I/O, and no input is ever modified. See docs/ROUTE_REQUIREMENTS.md.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace

import cv2
import numpy as np

from control.astar import grid_search

CELL_PX = 8                   # side of one planning cell; 720 x 1280 becomes a 90 x 160 grid
CELL_CENTRE_PX = CELL_PX // 2  # the pixel inside each cell that stands for the whole cell
MIN_HALF_WIDTH_PX = 2.0       # the chair never gets thinner than this, even at the horizon
START_BAND_FRACTION = 0.05    # the route must start in the bottom 5 percent of the image (the chair)

# A point on a grid step is at most half a diagonal step from a cell centre. Walking that far can lose that
# many pixels of clearance, and the chair can also get wider (width_gain px per row). Asking every cell centre
# for this much spare room therefore guarantees the whole step between two good cells is clear, not only its
# two ends. See `_grid_margin`.
HALF_DIAGONAL_PX = CELL_PX * math.sqrt(2) / 2
TARGET_KEEPOUT_PX = 6         # cells this close to the target are closed, so no step can clip it (> half diagonal)

COMFORT_FRACTION = 0.25       # spare room of a quarter of the chair's half-width counts as "comfortable"
CROWDING_WEIGHT = 0.5         # extra cost, in cell steps, of entering a cell with no spare room at all
BEYOND_TARGET_HALF_WIDTHS = 1.0  # the route may go at most this many chair half-widths farther than the target

STOP_GAP_SLACK_PX = 32.0      # the stop point may be one chair half-width plus this far from the target's base
TARGET_BASE_FRACTION = 0.1    # the lowest tenth of the target mask is its "base" (where it meets the floor)
VIA_MAX_DETOUR = 1.5          # Gemini's via-points are used only if the route gets at most this much longer

CHECK_STEP_PX = 1.0           # spacing of the check points along a route in the final check
SMOOTH_STEP_PX = 2.0          # coarser spacing while smoothing, which keeps margins of 3 px and more
CLEARANCE_TOLERANCE_PX = 1.0  # a sample is rounded to a pixel (up to 0.7 px off), so allow one pixel
SHORTCUT_TOLERANCE_PX = 2.0   # a shortcut may be this much tighter than the grid path it replaces
SHORTCUT_STRIDE = 4           # cells a shortcut is stretched by per check (1 would be exact but 4 times slower)
ROUNDING_SPARE_PX = 3.0       # a rounded corner must keep this much more room than the bare minimum
CORNER_CUTS_PX = (40.0, 20.0, 10.0)  # how far before a corner the curve may start; the largest that fits wins
CORNER_ARC_POINTS = 6         # points drawn along one rounded corner

WidthAt = Callable[[np.ndarray], np.ndarray]    # image rows -> chair half-width in pixels
ClearCheck = Callable[[np.ndarray], bool]       # (N, 2) polyline -> True if the chair fits all along it
ShortcutCheck = Callable[[np.ndarray, float], bool]  # (line, spare room of the path it replaces) -> take it?


@dataclass(frozen=True)
class Route:
    points: np.ndarray         # (N, 2) float pixels, from the chair (bottom edge) to the stop point
    half_width_px: np.ndarray  # (N,) chair half-width in pixels at each point (for drawing the ribbon)
    via_gemini: bool           # True if Gemini's suggested via-points were used


@dataclass(frozen=True)
class _Scene:
    """The masks a route is checked against, with the two things that are slow to compute done once."""
    free: np.ndarray                    # bool: floor the chair may be on
    target: np.ndarray                  # bool: the chosen object
    clearance: np.ndarray               # float: px from each pixel to the nearest non-free, non-target pixel
    anchor: tuple[float, float] | None  # (x, y) just below the target's base; None if the target mask is empty


@dataclass(frozen=True)
class _Grid:
    """The coarse planning grid: one cell per CELL_PX x CELL_PX block of pixels."""
    safe: np.ndarray      # bool (rows, cols): the chair fits here with the grid margin to spare
    near_target: np.ndarray  # bool, full frame size: the target grown by TARGET_KEEPOUT_PX
    crowding: np.ndarray  # float (rows, cols): extra cost of entering the cell, 0 where there is plenty of room
    xs: np.ndarray        # pixel x of each grid column's centre
    ys: np.ndarray        # pixel y of each grid row's centre


# ---------------------------------------------------------------- masks

def polygons_to_mask(polygons: Sequence[np.ndarray], shape: tuple[int, int]) -> np.ndarray:
    """Fill a list of (N, 2) pixel polygons (x, y) into one bool mask of `shape` (height, width)."""
    mask = np.zeros(shape[:2], dtype=np.uint8)
    for polygon in polygons:
        corners = np.asarray(polygon, dtype=float)
        if corners.ndim != 2 or corners.shape[1] != 2:
            raise ValueError(f"a polygon must be an (N, 2) array of x, y pixels, got shape {corners.shape}")
        if len(corners) >= 3:  # one or two points enclose no area, so they add nothing
            cv2.fillPoly(mask, [np.rint(corners).astype(np.int32)], 1)
    return mask.astype(bool)


def local_floor(shape: tuple[int, int], horizon_row: float) -> np.ndarray:
    """Fallback floor when Gemini has not answered: every pixel below the horizon row."""
    height, width = shape[:2]
    below = np.arange(height) > horizon_row
    return np.repeat(below[:, None], width, axis=1)


def half_width_px(rows: np.ndarray, horizon_row: float, width_gain: float) -> np.ndarray:
    """Chair half-width in pixels at each image row: width_gain * (row - horizon_row), at least 2 px.

    A flat floor seen by a level camera puts ground that is twice as close twice as far below the horizon,
    and things twice as close look twice as wide. So the chair's width in pixels grows in a straight line
    with the row. width_gain = chair half-width in metres / camera height in metres.
    """
    return np.maximum(MIN_HALF_WIDTH_PX, width_gain * (np.asarray(rows, dtype=float) - horizon_row))


def free_floor(floor: np.ndarray, objects: np.ndarray, no_go: np.ndarray) -> np.ndarray:
    """Floor the chair may drive on: floor AND NOT objects AND NOT no-go.

    C5: objects come from the on-device detector and are removed last, whatever the floor mask says. Gemini
    can take floor away (through `floor` or `no_go`) but can never add floor on top of a detected object.
    """
    floor, objects, no_go = (np.asarray(mask, dtype=bool) for mask in (floor, objects, no_go))
    if not floor.shape == objects.shape == no_go.shape:
        raise ValueError(f"mask shapes differ: floor {floor.shape}, objects {objects.shape}, no_go {no_go.shape}")
    return floor & ~objects & ~no_go


def _as_masks(free: np.ndarray, target: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    free, target = np.asarray(free, dtype=bool), np.asarray(target, dtype=bool)
    if free.ndim != 2 or free.shape != target.shape:
        raise ValueError(f"free and target must be 2-D masks of one shape, got {free.shape} and {target.shape}")
    return free, target


def _target_anchor(target: np.ndarray) -> tuple[float, float] | None:
    """(x, y) of the floor just below the middle of the target's base, or None for an empty mask."""
    rows = np.flatnonzero(target.any(axis=1))
    if rows.size == 0:
        return None
    top, bottom = int(rows[0]), int(rows[-1])
    base_rows = max(1, round(TARGET_BASE_FRACTION * (bottom - top + 1)))
    base_cols = np.flatnonzero(target[bottom - base_rows + 1:bottom + 1].any(axis=0))
    return (float(base_cols[0] + base_cols[-1]) / 2, bottom + 1.0)


def _make_scene(free: np.ndarray, target: np.ndarray) -> _Scene:
    # distanceTransform gives each non-zero pixel its distance to the nearest zero pixel. Zero here means
    # "neither free floor nor target", so the target does not count as an obstacle (the route has to end
    # right next to it) and neither does the image border (pixels outside the image are simply not there).
    drivable_or_target = (free | target).astype(np.uint8)
    clearance = cv2.distanceTransform(drivable_or_target, cv2.DIST_L2, cv2.DIST_MASK_PRECISE)
    return _Scene(free=free, target=target, clearance=clearance, anchor=_target_anchor(target))


# ---------------------------------------------------------------- checking a route (C1, C2, C3)

def route_violations(points: np.ndarray, half_widths: np.ndarray, free: np.ndarray,
                     target: np.ndarray) -> list[str]:
    """Every broken constraint of a route as one readable line each; an empty list means C1, C2, C3 hold.

    The segments between the points are checked too (a sample every CHECK_STEP_PX), not only the points.
    """
    free, target = _as_masks(free, target)
    points, half_widths = np.asarray(points, dtype=float), np.asarray(half_widths, dtype=float)
    well_formed = (points.ndim == 2 and points.shape[1] == 2 and len(points) >= 2
                   and half_widths.shape == (len(points),)
                   and np.isfinite(points).all() and np.isfinite(half_widths).all())
    if not well_formed:
        return ["route is malformed: it needs at least 2 finite (x, y) points and one half-width per point"]
    return _violations(points, half_widths, _make_scene(free, target))


def _violations(points: np.ndarray, half_widths: np.ndarray, scene: _Scene) -> list[str]:
    samples, widths = _sample_polyline(points, half_widths, CHECK_STEP_PX)
    spare = _spare_room(samples, widths, scene)
    off_floor = np.isneginf(spare)
    too_tight = ~off_floor & (spare < -CLEARANCE_TOLERANCE_PX)
    problems = []
    if off_floor.any():
        x, y = samples[np.argmax(off_floor)]
        problems.append(f"C1: route leaves the free floor at x={x:.0f}, y={y:.0f} "
                        f"({int(off_floor.sum())} of {len(samples)} check points are off it)")
    if too_tight.any():
        worst = int(np.argmin(np.where(too_tight, spare, np.inf)))
        x, y = samples[worst]
        problems.append(f"C2: chair does not fit at x={x:.0f}, y={y:.0f}: it needs {widths[worst]:.0f} px of "
                        f"free floor on each side and has {widths[worst] + spare[worst]:.0f} px")
    return problems + _end_violations(points, half_widths, scene)


def _end_violations(points: np.ndarray, half_widths: np.ndarray, scene: _Scene) -> list[str]:
    """C3: the route starts under the chair and stops on the floor next to the target."""
    height = scene.free.shape[0]
    band_top = height * (1 - START_BAND_FRACTION)
    problems = []
    if points[0, 1] < band_top:
        problems.append(f"C3: route starts at y={points[0, 1]:.0f}, not at the bottom edge of the image "
                        f"(y >= {band_top:.0f})")
    if scene.anchor is None:
        return problems + ["C3: there is no target to stop in front of (the target mask is empty)"]
    end_x, end_y = points[-1]
    row, col = int(round(end_y)), int(round(end_x))
    if 0 <= row < height and 0 <= col < scene.free.shape[1] and scene.target[row, col]:
        problems.append("C3: route ends on the target instead of on the floor in front of it")
    gap = math.hypot(end_x - scene.anchor[0], end_y - scene.anchor[1])
    limit = _stop_gap_limit(float(half_widths[-1]))
    if gap > limit:
        problems.append(f"C3: route ends {gap:.0f} px from the target's base, more than the {limit:.0f} px allowed")
    return problems


def _stop_gap_limit(half_width: np.ndarray | float) -> np.ndarray | float:
    """How far from the target's base the stop point may be, given the chair's half-width at the stop point.

    The clearance rule can force the chair to stop one half-width short of whatever is behind the target
    (a wall, say), so that much must be allowed; the slack covers the grid's coarseness.
    """
    return half_width + STOP_GAP_SLACK_PX


def _sample_polyline(points: np.ndarray, values: np.ndarray, step: float) -> tuple[np.ndarray, np.ndarray]:
    """Points every `step` pixels along a polyline (corners included), with `values` interpolated to match."""
    lengths = np.hypot(*np.diff(points, axis=0).T)
    along = np.concatenate([[0.0], np.cumsum(lengths)])  # distance travelled when each corner is reached
    count = max(2, math.ceil(along[-1] / step) + 1)
    at = np.concatenate([np.linspace(0.0, along[-1], count), along[1:-1]])  # even steps, plus every corner
    samples = np.column_stack([np.interp(at, along, points[:, 0]), np.interp(at, along, points[:, 1])])
    return samples, np.interp(at, along, values)


def _spare_room(samples: np.ndarray, widths: np.ndarray, scene: _Scene) -> np.ndarray:
    """For each (x, y) sample: clearance minus chair half-width, in px. Minus infinity where it is off the floor."""
    height, width = scene.free.shape
    cols, rows = np.rint(samples[:, 0]).astype(np.intp), np.rint(samples[:, 1]).astype(np.intp)
    inside = (rows >= 0) & (rows < height) & (cols >= 0) & (cols < width)
    rows, cols = rows * inside, cols * inside  # samples outside the image look up pixel (0, 0); they fail anyway
    on_floor = inside & scene.free[rows, cols] & ~scene.target[rows, cols]
    return np.where(on_floor, scene.clearance[rows, cols] - widths, -np.inf)


def _spare_along(points: np.ndarray, scene: _Scene, width_at: WidthAt) -> tuple[np.ndarray, np.ndarray]:
    """Spare room and chair half-width at check points all along a polyline (segments included)."""
    samples, widths = _sample_polyline(points, width_at(points[:, 1]), SMOOTH_STEP_PX)
    return _spare_room(samples, widths, scene), widths


# ---------------------------------------------------------------- the planning grid

def _grid_margin(width_gain: float) -> float:
    """Spare room a cell centre needs so that every step to a neighbouring good cell is clear along its length."""
    return HALF_DIAGONAL_PX * (1.0 + width_gain)


def _build_grid(scene: _Scene, width_at: WidthAt, margin: float) -> _Grid:
    height, width = scene.free.shape
    ys, xs = np.arange(CELL_CENTRE_PX, height, CELL_PX), np.arange(CELL_CENTRE_PX, width, CELL_PX)
    centres = (slice(CELL_CENTRE_PX, None, CELL_PX), slice(CELL_CENTRE_PX, None, CELL_PX))
    half_width = width_at(ys)[:, None]  # one value per grid row; the chair is equally wide along a row
    spare = scene.clearance[centres] - half_width - margin
    # Grow the target by a few pixels and close every cell it then covers: a step between two open cells
    # can no longer clip a thin part of the target (a chair leg) that lies between their centres.
    reach = 2 * TARGET_KEEPOUT_PX + 1
    near_target = cv2.dilate(scene.target.astype(np.uint8), np.ones((reach, reach), dtype=np.uint8)).astype(bool)
    # Rows above the target's base are floor that is farther away than the target. A pixel up there covers
    # a lot of real floor, so a route that swings round behind the target looks short in pixels while being
    # a long drive. The chair has no reason to go there: the stop point is in front of the target.
    anchor_row = scene.anchor[1]
    not_beyond = ys >= anchor_row - BEYOND_TARGET_HALF_WIDTHS * float(width_at(np.array([anchor_row]))[0])
    safe = scene.free[centres] & (spare >= 0) & ~near_target[centres] & not_beyond[:, None]
    # 1 when the chair only just fits, falling to 0 once there is a comfortable amount of room to spare.
    crowding = CROWDING_WEIGHT * np.clip(1.0 - spare / (COMFORT_FRACTION * half_width), 0.0, 1.0)
    return _Grid(safe=safe, near_target=near_target, crowding=crowding, xs=xs, ys=ys)


def _start_cell(grid: _Grid, frame_shape: tuple[int, int]) -> tuple[int, int] | None:
    """The safe cell in the bottom band closest to the centre column (the chair looks straight ahead)."""
    height, width = frame_shape
    in_band = grid.ys >= height * (1 - START_BAND_FRACTION)
    rows, cols = np.nonzero(grid.safe & in_band[:, None])
    if rows.size == 0:
        return None
    off_centre = np.abs(grid.xs[cols] - (width - 1) / 2)
    best = np.lexsort((-rows, off_centre))[0]  # nearest the centre first; on a tie, the lowest row
    return int(rows[best]), int(cols[best])


def _reachable_from(safe: np.ndarray, start: tuple[int, int]) -> np.ndarray:
    """The safe cells joined to `start` by safe cells (diagonals count). The rest can never be driven to."""
    _, labels = cv2.connectedComponents(safe.astype(np.uint8), connectivity=8)
    return labels == labels[start]


def _goal_cell(reachable: np.ndarray, grid: _Grid, anchor: tuple[float, float],
               width_at: WidthAt) -> tuple[int, int] | None:
    """The reachable cell nearest the floor just below the target's base, if one is close enough to it."""
    gap = np.hypot(grid.xs[None, :] - anchor[0], grid.ys[:, None] - anchor[1])
    allowed = reachable & (gap <= _stop_gap_limit(width_at(grid.ys))[:, None])
    if not allowed.any():
        return None
    row, col = np.unravel_index(np.argmin(np.where(allowed, gap, np.inf)), gap.shape)
    return int(row), int(col)


def _via_cells(via: np.ndarray | None, reachable: np.ndarray) -> list[tuple[int, int]] | None:
    """Grid cells of Gemini's via-points, or None unless every single point lies in a reachable cell."""
    if via is None:
        return None
    try:
        points = np.asarray(via, dtype=float)
    except (TypeError, ValueError):
        return None
    if points.ndim != 2 or points.shape[1] != 2 or len(points) == 0 or not np.isfinite(points).all():
        return None
    cols, rows = (np.floor(points[:, axis] / CELL_PX).astype(np.intp) for axis in (0, 1))
    n_rows, n_cols = reachable.shape
    inside = (rows >= 0) & (rows < n_rows) & (cols >= 0) & (cols < n_cols)
    if not inside.all() or not reachable[rows, cols].all():
        return None
    return list(zip(rows.tolist(), cols.tolist()))


def _plan_legs(grid: _Grid, reachable: np.ndarray, start: tuple[int, int], goal: tuple[int, int],
               via: np.ndarray | None) -> tuple[list[np.ndarray], bool]:
    """The route as one or more legs of (N, 2) pixel points, and whether Gemini's via-points were used."""
    def leg(a: tuple[int, int], b: tuple[int, int]) -> np.ndarray | None:
        cells = grid_search(~reachable, a, b, extra_cost=grid.crowding)
        return None if cells is None else _cell_centres(grid, cells)

    direct = leg(start, goal)
    if direct is None:  # cannot happen (both cells are in one connected piece), but never assume a path
        return [], False
    via_cells = _via_cells(via, reachable)
    if via_cells is None:
        return [direct], False
    stops = [start, *via_cells, goal]
    longest_allowed = VIA_MAX_DETOUR * _length(direct)
    # No route through the via-points can be shorter than straight lines between them, so if even those
    # are too long the answer is already known and the searches (the slow part) can be skipped.
    if _length(_cell_centres(grid, stops)) > longest_allowed:
        return [direct], False
    legs = [leg(a, b) for a, b in zip(stops, stops[1:])]
    if any(one is None for one in legs) or sum(map(_length, legs)) > longest_allowed:
        return [direct], False
    return legs, True


def _cell_centres(grid: _Grid, cells: Sequence[tuple[int, int]]) -> np.ndarray:
    """(N, 2) pixel (x, y) of the centres of a list of (row, col) grid cells."""
    return np.array([(grid.xs[col], grid.ys[row]) for row, col in cells], dtype=float)


def _length(points: np.ndarray) -> float:
    return float(np.hypot(*np.diff(points, axis=0).T).sum())


def _join(legs: list[np.ndarray]) -> np.ndarray:
    """Legs end to end as one polyline; each later leg starts where the one before ended, so skip that point."""
    return np.concatenate([legs[0], *(leg[1:] for leg in legs[1:])])


# ---------------------------------------------------------------- smoothing

def _string_pull(points: np.ndarray, spare: np.ndarray, is_shortcut_ok: ShortcutCheck) -> np.ndarray:
    """Replace the grid's zig-zag with straight runs wherever the straight line is fine ("string pulling").

    Walk along the path holding one end of a string at `anchor`. As long as the straight line from the anchor
    to a point further on is fine, keep going; when it is not, pin the string at the last point that was
    reached and continue from there. Every straight run that is kept has therefore been checked. `spare[k]`
    is the spare room at point k; the tightest spot of the stretch being replaced is passed to the check, so
    a shortcut is refused when it would squeeze closer to an obstacle than the grid path did.
    """
    last = len(points) - 1
    kept, anchor, reached = [points[0]], 0, min(1, last)  # the step to the very next cell is always fine
    while reached < last:
        for stride in (SHORTCUT_STRIDE, 1):  # try a long stretch first; if that fails, a single cell
            probe = min(reached + stride, last)
            if is_shortcut_ok(points[[anchor, probe]], float(spare[anchor:probe + 1].min())):
                reached = probe
                break
        else:  # the line from the anchor cannot be stretched any further: pin the string here
            kept.append(points[reached])
            anchor, reached = reached, reached + 1
    kept.append(points[-1])
    return np.array(kept)


def _rounded_corner(before: np.ndarray, corner: np.ndarray, after: np.ndarray, is_clear: ClearCheck) -> np.ndarray:
    """A short curve that replaces one corner, or the corner itself if no curve is clear."""
    to_before, to_after = before - corner, after - corner
    len_before, len_after = float(np.hypot(*to_before)), float(np.hypot(*to_after))
    turn = to_before[0] * to_after[1] - to_before[1] * to_after[0]  # zero when the three points are in line
    if min(len_before, len_after) < 1e-6 or abs(turn) < 1e-6 * len_before * len_after:
        return corner[None, :]
    # Use at most half of each neighbouring segment, so the curves of two corners in a row cannot overlap.
    longest_cut = 0.5 * min(len_before, len_after)
    t = np.linspace(0.0, 1.0, CORNER_ARC_POINTS)[:, None]
    tried = None
    for cut in CORNER_CUTS_PX:
        cut = min(cut, longest_cut)
        if cut == tried:  # the segments are so short that this is the same curve as the one just rejected
            break
        tried = cut
        enter, leave = corner + to_before / len_before * cut, corner + to_after / len_after * cut
        # Quadratic Bezier: starts at `enter`, ends at `leave`, pulled towards the corner in between.
        arc = (1 - t) ** 2 * enter + 2 * (1 - t) * t * corner + t ** 2 * leave
        if is_clear(arc):
            return arc
    return corner[None, :]


def _smooth(legs: list[np.ndarray], scene: _Scene, width_at: WidthAt, margin: float) -> np.ndarray:
    """Straighten each leg, join the legs, then round the corners. Via-points stay on the route."""
    def is_shortcut_ok(line: np.ndarray, tightest: float) -> bool:
        # Allowed when the line has a comfortable amount of room, or at least as much as the grid path it
        # replaces had at its tightest spot. Either way never less than the grid's own margin. This keeps
        # the route in the middle of a corridor: a shortcut that drifts towards a wall is refused.
        spare, widths = _spare_along(line, scene, width_at)
        needed = np.minimum(COMFORT_FRACTION * widths + margin, tightest - SHORTCUT_TOLERANCE_PX)
        return bool((spare >= np.maximum(needed, margin)).all())

    def is_curve_clear(curve: np.ndarray) -> bool:
        return bool((_spare_along(curve, scene, width_at)[0] >= ROUNDING_SPARE_PX).all())

    def cell_spare(leg: np.ndarray) -> np.ndarray:  # spare room at each cell centre of a grid leg
        return _spare_room(leg, width_at(leg[:, 1]), scene)

    pulled = _join([_string_pull(leg, cell_spare(leg), is_shortcut_ok) for leg in legs])
    pieces = [pulled[:1]]
    for before, corner, after in zip(pulled, pulled[1:], pulled[2:]):
        pieces.append(_rounded_corner(before, corner, after, is_curve_clear))
    pieces.append(pulled[-1:])
    return np.concatenate(pieces)


# ---------------------------------------------------------------- the planner

def _width_model(horizon_row: float, width_gain: float,
                 fixed_half_width_px: float | None) -> tuple[WidthAt, float]:
    """How wide the chair is at each row, and the grid margin that goes with it.

    Camera view (the default): the half-width grows with the row, see `half_width_px`.
    Top-down view (fixed_half_width_px given): the masks are a metric map of the floor, so the chair is
    equally wide on every row; horizon_row and width_gain are not looked at.
    """
    if fixed_half_width_px is None:
        if not (math.isfinite(horizon_row) and math.isfinite(width_gain) and width_gain > 0):
            raise ValueError(f"horizon_row must be finite and width_gain positive, got {horizon_row}, {width_gain}")
        return (lambda rows: half_width_px(rows, horizon_row, width_gain)), _grid_margin(width_gain)
    if not (math.isfinite(fixed_half_width_px) and fixed_half_width_px > 0):
        raise ValueError(f"fixed_half_width_px must be a positive number of pixels, got {fixed_half_width_px}")
    width = float(fixed_half_width_px)
    # A gain of zero in the margin: the chair does not get wider along a grid step in this view.
    return (lambda rows: np.full(np.shape(rows), width)), _grid_margin(0.0)


def plan_route(free: np.ndarray, target: np.ndarray, horizon_row: float, width_gain: float,
               via: np.ndarray | None = None, fixed_half_width_px: float | None = None) -> Route | None:
    """A checked route from the chair to the floor in front of `target`, or None when there is no safe route (C4).

    free:        bool mask of drivable floor (see `free_floor`)
    target:      bool mask of the chosen object
    horizon_row: image row of the horizon (where the floor would vanish)
    width_gain:  chair half-width in metres / camera height in metres (0.3 / 1.0 by default)
    via:         optional (N, 2) points suggested by Gemini; used only if they pass the same checks
    fixed_half_width_px: give this when the masks are a top-down metric view of the floor (chair at the
                 bottom centre, far at the top). Every row then uses this half-width, and horizon_row and
                 width_gain are ignored. Everything else works the same.
    """
    free, target = _as_masks(free, target)
    width_at, margin = _width_model(horizon_row, width_gain, fixed_half_width_px)
    scene = _make_scene(free, target)
    if scene.anchor is None:
        return None
    grid = _build_grid(scene, width_at, margin)
    start = _start_cell(grid, free.shape)
    if start is None:
        return None  # no room for the chair on the floor at the bottom edge
    reachable = _reachable_from(grid.safe, start)
    goal = _goal_cell(reachable, grid, scene.anchor, width_at)
    if goal is None:
        return None  # no reachable floor close enough to the target
    legs, via_used = _plan_legs(grid, reachable, start, goal, via)
    if not legs:
        return None

    # While smoothing, the grown target counts as the target: a shortcut or a rounded corner must stay as
    # far from it as the grid cells do. (The target is exempt from the clearance rule, so nothing else
    # would stop a shortcut from clipping its corner.)
    smoothed = _smooth(legs, replace(scene, target=grid.near_target), width_at, margin)
    for points in (smoothed, _join(legs)):  # the smooth route first; the plain grid route as the fallback
        half_widths = width_at(points[:, 1])
        if not _violations(points, half_widths, scene):
            return Route(points=points, half_width_px=half_widths, via_gemini=via_used)
    return None  # C4: nothing passed the check, so nothing is returned
