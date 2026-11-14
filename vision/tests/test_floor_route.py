"""Image-space route planner (vision/floor_route.py): constraints C1 to C5 of docs/ROUTE_REQUIREMENTS.md.

The masks here are small synthetic scenes (240 x 320) so every test runs in milliseconds. The checks on the
planned route use their own brute-force geometry (`_gap_to`), not the planner's helpers, so a bug shared by the
planner and its validator still fails a test.
"""

import dataclasses

import numpy as np
import pytest

from vision.floor_route import (
    Route,
    free_floor,
    half_width_px,
    local_floor,
    plan_route,
    polygons_to_mask,
    route_violations,
)

H, W = 240, 320
HORIZON = 80.0  # image row of the horizon: the chair has zero width there
GAIN = 0.3      # chair half-width grows 0.3 px per row below the horizon
SHAPE = (H, W)
BOTTOM_BAND_TOP = H * 0.95  # the route must start in the bottom 5 percent of the image


def _box(top: int, bottom: int, left: int, right: int) -> np.ndarray:
    """A filled rectangle mask; all four edges are inclusive."""
    mask = np.zeros(SHAPE, dtype=bool)
    mask[top:bottom + 1, left:right + 1] = True
    return mask


NOTHING = np.zeros(SHAPE, dtype=bool)
TARGET = _box(90, 110, 150, 170)       # the chosen object, standing on the floor far from the chair
OBSTACLE = _box(150, 180, 110, 185)    # sits between the chair and the target, a little left of centre
TARGET_BOTTOM_CENTRE = np.array([160.0, 110.0])


def _scene(obstacles: np.ndarray = NOTHING, floor: np.ndarray | None = None) -> np.ndarray:
    """Free floor for a scene: the floor below the horizon minus the target and any obstacles."""
    floor = local_floor(SHAPE, HORIZON) if floor is None else floor
    return free_floor(floor, TARGET | obstacles, NOTHING)


def _dense(points: np.ndarray, step: float = 0.5) -> np.ndarray:
    """Points every `step` pixels along the polyline, so the segments are checked and not only the corners."""
    pieces = []
    for a, b in zip(points, points[1:]):
        count = max(2, int(np.hypot(*(b - a)) / step) + 1)
        pieces.append(np.linspace(a, b, count))
    return np.concatenate(pieces)


def _gap_to(mask: np.ndarray, samples: np.ndarray) -> np.ndarray:
    """Brute-force distance in pixels from each (x, y) sample to the nearest True pixel of `mask`."""
    ys, xs = np.nonzero(mask)
    return np.hypot(samples[:, None, 0] - xs[None, :], samples[:, None, 1] - ys[None, :]).min(axis=1)


def _on(mask: np.ndarray, samples: np.ndarray) -> np.ndarray:
    """True for each (x, y) sample whose nearest pixel is set in `mask`."""
    return mask[np.rint(samples[:, 1]).astype(int), np.rint(samples[:, 0]).astype(int)]


def _length(points: np.ndarray) -> float:
    return float(np.hypot(*np.diff(points, axis=0).T).sum())


# ---------------------------------------------------------------- small helpers of the module

def test_half_width_grows_linearly_below_the_horizon_and_never_drops_under_two_pixels():
    rows = np.array([0.0, 80.0, 90.0, 180.0, 240.0])

    widths = half_width_px(rows, HORIZON, GAIN)

    assert widths == pytest.approx([2.0, 2.0, 3.0, 30.0, 48.0])


def test_local_floor_is_everything_below_the_horizon_row():
    floor = local_floor(SHAPE, HORIZON)

    assert floor.shape == SHAPE and floor.dtype == bool
    assert not floor[:81].any() and floor[81:].all()


def test_polygons_to_mask_fills_each_polygon_and_nothing_else():
    square = np.array([[10, 20], [30, 20], [30, 40], [10, 40]], dtype=float)
    triangle = np.array([[100, 100], [140, 100], [120, 130]], dtype=float)

    mask = polygons_to_mask([square, triangle], SHAPE)

    assert mask.shape == SHAPE and mask.dtype == bool
    assert mask[30, 20] and mask[110, 120]          # (row, col) inside the square and the triangle
    assert not mask[30, 60] and not mask[200, 200]  # outside both


def test_polygons_to_mask_with_no_polygons_is_empty():
    assert not polygons_to_mask([], SHAPE).any()


def test_free_floor_removes_objects_and_no_go_zones_from_the_floor():
    floor = local_floor(SHAPE, HORIZON)
    no_go = _box(200, 220, 10, 40)

    free = free_floor(floor, OBSTACLE, no_go)

    assert not free[OBSTACLE].any() and not free[no_go].any()
    assert free[230, 160] and not free[10, 10]  # open floor stays free; above the horizon was never floor


def test_gemini_floor_drawn_over_an_object_does_not_make_the_object_drivable():  # C5
    gemini_floor = np.ones(SHAPE, dtype=bool)  # Gemini wrongly calls the whole picture floor

    free = free_floor(gemini_floor, TARGET | OBSTACLE, NOTHING)
    route = plan_route(free, TARGET, HORIZON, GAIN)

    assert not free[OBSTACLE].any() and not free[TARGET].any()
    assert route is not None
    assert not _on(OBSTACLE | TARGET, _dense(route.points)).any()


# ---------------------------------------------------------------- plan_route

def test_open_floor_gives_a_route_from_the_bottom_edge_to_just_below_the_target():
    free = _scene()

    route = plan_route(free, TARGET, HORIZON, GAIN)

    assert isinstance(route, Route) and not route.via_gemini
    start, end = route.points[0], route.points[-1]
    assert start[1] >= BOTTOM_BAND_TOP and abs(start[0] - W / 2) <= 8  # starts under the chair (C3)
    assert end[1] > 110 and not _on(TARGET, route.points[-1:])[0]        # ends below the target, not on it
    assert np.hypot(*(end - TARGET_BOTTOM_CENTRE)) <= 40                 # and close to it
    assert route.points.shape[1] == 2 and route.half_width_px.shape == (len(route.points),)
    assert route.half_width_px == pytest.approx(half_width_px(route.points[:, 1], HORIZON, GAIN))
    assert route_violations(route.points, route.half_width_px, free, TARGET) == []


def test_open_floor_route_is_close_to_a_straight_line():
    route = plan_route(_scene(), TARGET, HORIZON, GAIN)

    straight = float(np.hypot(*(route.points[-1] - route.points[0])))
    assert _length(route.points) <= 1.05 * straight


def test_object_between_chair_and_target_forces_a_detour_that_never_touches_it():
    free = _scene(OBSTACLE)

    route = plan_route(free, TARGET, HORIZON, GAIN)

    assert route is not None
    samples = _dense(route.points)
    assert _on(free, samples).all()                                             # C1: always on free floor
    assert not _on(OBSTACLE, samples).any()
    needed = half_width_px(samples[:, 1], HORIZON, GAIN)
    assert (_gap_to(OBSTACLE, samples) >= needed - 1.0).all()                   # C2: the chair fits beside it
    assert _length(route.points) > np.hypot(*(route.points[-1] - route.points[0])) + 5  # longer than straight
    assert route_violations(route.points, route.half_width_px, free, TARGET) == []


def test_route_keeps_half_a_chair_width_from_the_edge_of_the_floor():
    floor = local_floor(SHAPE, HORIZON) & ~_box(0, H - 1, 0, 99)  # no floor in the left third of the picture
    free = free_floor(floor, TARGET, NOTHING)

    route = plan_route(free, TARGET, HORIZON, GAIN)

    assert route is not None
    samples = _dense(route.points)
    assert (_gap_to(~floor, samples) >= half_width_px(samples[:, 1], HORIZON, GAIN) - 1.0).all()


def test_corridor_narrower_than_the_chair_returns_none():
    # Rows 150..180 have floor only in a 20 px wide gap; the chair is about 50 px wide there.
    narrow = _box(150, 180, 0, 149) | _box(150, 180, 171, W - 1)

    route = plan_route(_scene(narrow), TARGET, HORIZON, GAIN)

    assert route is None


def test_corridor_wider_than_the_chair_is_driven_through_its_middle():
    wide = _box(150, 180, 0, 99) | _box(150, 180, 221, W - 1)  # a 120 px gap centred on column 160
    free = _scene(wide)

    route = plan_route(free, TARGET, HORIZON, GAIN)

    assert route is not None
    samples = _dense(route.points)
    in_gap = samples[(samples[:, 1] >= 150) & (samples[:, 1] <= 180)]
    assert len(in_gap) > 0 and (np.abs(in_gap[:, 0] - 160) <= 20).all()
    assert route_violations(route.points, route.half_width_px, free, TARGET) == []


def test_wall_of_objects_across_the_floor_returns_none():
    wall = _box(150, 160, 0, W - 1)

    assert plan_route(_scene(wall), TARGET, HORIZON, GAIN) is None


def test_no_go_zone_across_the_floor_returns_none():
    floor = local_floor(SHAPE, HORIZON)
    free = free_floor(floor, TARGET, _box(150, 160, 0, W - 1))

    assert plan_route(free, TARGET, HORIZON, GAIN) is None


def test_floor_missing_under_the_chair_returns_none():
    floor = local_floor(SHAPE, HORIZON) & ~_box(200, H - 1, 0, W - 1)  # Gemini saw no floor near the chair

    assert plan_route(_scene(floor=floor), TARGET, HORIZON, GAIN) is None


def test_no_floor_in_front_of_the_target_returns_none():
    # The target stands on a table: everything around and below it, down to row 170, is a no-go zone.
    table = _box(85, 170, 60, 260)
    free = free_floor(local_floor(SHAPE, HORIZON), TARGET, table)

    assert plan_route(free, TARGET, HORIZON, GAIN) is None


def test_empty_target_mask_returns_none():
    assert plan_route(_scene(), NOTHING, HORIZON, GAIN) is None


def test_masks_of_different_shapes_are_rejected_with_a_clear_error():
    with pytest.raises(ValueError):
        plan_route(_scene(), np.zeros((10, 10), dtype=bool), HORIZON, GAIN)


# ---------------------------------------------------------------- Gemini's via-points

VIA_LEFT = np.array([[60.0, 165.0]])  # on open floor to the LEFT of the obstacle; the direct route goes right


def test_direct_route_passes_the_obstacle_on_its_shorter_right_side():
    route = plan_route(_scene(OBSTACLE), TARGET, HORIZON, GAIN)

    samples = _dense(route.points)
    beside = samples[(samples[:, 1] >= 150) & (samples[:, 1] <= 180)]
    assert not route.via_gemini and (beside[:, 0] > 185).all()


def test_valid_via_points_are_used_and_the_route_passes_through_them():
    free = _scene(OBSTACLE)

    route = plan_route(free, TARGET, HORIZON, GAIN, via=VIA_LEFT)

    assert route is not None and route.via_gemini
    samples = _dense(route.points)
    beside = samples[(samples[:, 1] >= 150) & (samples[:, 1] <= 180)]
    assert (beside[:, 0] < 110).all()                                   # now on the left of the obstacle
    assert np.hypot(*(samples - VIA_LEFT[0]).T).min() <= 16             # and through Gemini's point
    assert route_violations(route.points, route.half_width_px, free, TARGET) == []


@pytest.mark.parametrize("bad_via, reason", [
    (np.array([[60.0, 165.0], [150.0, 165.0]]), "second point is on the obstacle"),
    (np.array([[160.0, 100.0]]), "point is on the target"),
    (np.array([[160.0, 40.0]]), "point is above the horizon, off the floor"),
    (np.array([[500.0, 165.0]]), "point is outside the picture"),
    (np.array([[np.nan, 165.0]]), "point is not a number"),
    (np.array([[20.0, 230.0], [300.0, 230.0]]), "route through them is more than 1.5 times the direct route"),
    (np.array([1.0, 2.0, 3.0]), "not an (N, 2) array"),
    (np.zeros((0, 2)), "no points at all"),
])
def test_invalid_via_points_are_ignored_and_the_direct_route_is_returned(bad_via, reason):
    free = _scene(OBSTACLE)
    direct = plan_route(free, TARGET, HORIZON, GAIN)

    route = plan_route(free, TARGET, HORIZON, GAIN, via=bad_via)

    assert route is not None and not route.via_gemini, reason
    assert np.array_equal(route.points, direct.points), reason


def test_inputs_are_not_modified():
    free, target, via = _scene(OBSTACLE), TARGET.copy(), VIA_LEFT.copy()
    floor, objects, no_go = local_floor(SHAPE, HORIZON), OBSTACLE.copy(), _box(200, 220, 10, 40)
    before = [a.copy() for a in (free, target, via, floor, objects, no_go)]

    free_floor(floor, objects, no_go)
    route = plan_route(free, target, HORIZON, GAIN, via=via)
    route_violations(route.points, route.half_width_px, free, target)

    for original, now in zip(before, (free, target, via, floor, objects, no_go)):
        assert np.array_equal(original, now)


def test_route_is_a_frozen_dataclass():
    route = plan_route(_scene(), TARGET, HORIZON, GAIN)

    with pytest.raises(dataclasses.FrozenInstanceError):
        route.via_gemini = True


def test_planning_twice_gives_the_same_route():
    free = _scene(OBSTACLE)

    first, second = plan_route(free, TARGET, HORIZON, GAIN), plan_route(free, TARGET, HORIZON, GAIN)

    assert np.array_equal(first.points, second.points)


# ---------------------------------------------------------------- route_violations (hand-made routes)

def _line(*xy: tuple[float, float]) -> tuple[np.ndarray, np.ndarray]:
    points = np.array(xy, dtype=float)
    return points, half_width_px(points[:, 1], HORIZON, GAIN)


def _broken(violations: list[str]) -> set[str]:
    """The constraint numbers named at the start of each message, e.g. {"C1", "C3"}."""
    return {message.split(":")[0] for message in violations}


def test_straight_route_on_open_floor_has_no_violations():
    points, widths = _line((160, 239), (160, 124))

    assert route_violations(points, widths, _scene(), TARGET) == []


def test_segment_crossing_an_object_between_two_good_points_breaks_c1():
    centred = _box(150, 180, 130, 190)  # both end points are fine; only the line between them is not
    points, widths = _line((160, 239), (160, 124))

    violations = route_violations(points, widths, _scene(centred), TARGET)

    assert "C1" in _broken(violations)


def test_route_point_outside_the_picture_breaks_c1():
    points, widths = _line((160, 239), (400, 200), (160, 124))

    assert "C1" in _broken(route_violations(points, widths, _scene(), TARGET))


def test_route_squeezing_past_an_object_breaks_c2_but_not_c1():
    beside = _box(150, 180, 170, 200)  # 10 px right of the line; the chair needs about 25 px there
    points, widths = _line((160, 239), (160, 124))

    violations = route_violations(points, widths, _scene(beside), TARGET)

    assert _broken(violations) == {"C2"}


def test_route_that_does_not_start_at_the_bottom_edge_breaks_c3():
    points, widths = _line((160, 200), (160, 124))

    assert _broken(route_violations(points, widths, _scene(), TARGET)) == {"C3"}


def test_route_that_ends_on_the_target_breaks_c3():
    points, widths = _line((160, 239), (160, 100))

    assert "C3" in _broken(route_violations(points, widths, _scene(), TARGET))


def test_route_that_ends_far_from_the_target_breaks_c3():
    points, widths = _line((160, 239), (160, 200))

    assert _broken(route_violations(points, widths, _scene(), TARGET)) == {"C3"}


def test_route_beside_the_target_is_allowed_because_the_target_is_exempt_from_clearance():
    # The end point is 8 px below the target and the chair's half-width is about 11 px there: if the target
    # counted as an obstacle it would be "too close", and no route could ever end next to it.
    points, widths = _line((160, 239), (160, 118))
    free = _scene()
    other_target = _box(125, 130, 100, 105)  # same free floor, but the box above the end point is not the target

    violations = route_violations(points, widths, free, TARGET)
    without_exemption = route_violations(points, widths, free, other_target)

    assert violations == []
    assert "C2" in _broken(without_exemption)


@pytest.mark.parametrize("points, widths", [
    (np.array([[160.0, 239.0]]), np.array([47.0])),                       # a single point is not a route
    (np.array([[160.0, 239.0], [160.0, 124.0]]), np.array([47.0])),       # one half-width is missing
    (np.array([[160.0, 239.0], [np.nan, 124.0]]), np.array([47.0, 13.0])),
])
def test_malformed_route_is_reported_not_crashed_on(points, widths):
    violations = route_violations(points, widths, _scene(), TARGET)

    assert len(violations) == 1 and "malformed" in violations[0]


# ---------------------------------------------------------------- top-down view (fixed_half_width_px)
# The caller warps the masks to a metric map of the floor (1 cm per pixel, chair at the bottom centre, far at
# the top). There the chair is equally wide on every row, so the planner is told one fixed half-width.

TOP_SHAPE = (450, 600)
CHAIR_HALF_PX = 30.0


def _top_box(top: int, bottom: int, left: int, right: int) -> np.ndarray:
    mask = np.zeros(TOP_SHAPE, dtype=bool)
    mask[top:bottom + 1, left:right + 1] = True
    return mask


TOP_TARGET = _top_box(60, 100, 280, 320)
TOP_WALL_WITH_50PX_GAP = _top_box(200, 220, 0, 274) | _top_box(200, 220, 325, 599)  # the gap is columns 275..324


def test_fixed_half_width_gives_a_route_with_that_constant_width_and_ignores_horizon_and_gain():
    free = ~TOP_TARGET  # the whole map is floor except the target

    route = plan_route(free, TOP_TARGET, 0.0, 0.3, fixed_half_width_px=CHAIR_HALF_PX)
    other_camera = plan_route(free, TOP_TARGET, 400.0, 0.9, fixed_half_width_px=CHAIR_HALF_PX)

    assert route is not None and (route.half_width_px == CHAIR_HALF_PX).all()
    start, end = route.points[0], route.points[-1]
    assert start[1] >= 450 * 0.95 and abs(start[0] - 300) <= 8             # under the chair, bottom centre
    assert 100 < end[1] <= 100 + 20 and abs(end[0] - 300) <= 8             # just below the target's base
    assert np.array_equal(route.points, other_camera.points)               # horizon_row and width_gain unused
    assert route_violations(route.points, route.half_width_px, free, TOP_TARGET) == []


def test_fixed_half_width_decides_whether_the_chair_fits_through_a_gap():
    free = ~(TOP_TARGET | TOP_WALL_WITH_50PX_GAP)

    slim = plan_route(free, TOP_TARGET, 0.0, 0.3, fixed_half_width_px=15.0)           # 30 px chair, 50 px gap
    wide = plan_route(free, TOP_TARGET, 0.0, 0.3, fixed_half_width_px=CHAIR_HALF_PX)  # 60 px chair, 50 px gap
    by_camera_rule = plan_route(free, TOP_TARGET, 0.0, 0.01)  # without the keyword the chair is ~2 px there

    assert wide is None
    assert by_camera_rule is not None            # shows the keyword, not the masks, made the difference
    assert slim is not None and (slim.half_width_px == 15.0).all()
    samples = _dense(slim.points)
    ys, xs = np.nonzero(TOP_WALL_WITH_50PX_GAP)
    gap = np.hypot(samples[:, None, 0] - xs[None, :], samples[:, None, 1] - ys[None, :]).min(axis=1)
    assert (gap >= 15.0 - 1.0).all()                                          # C2 with the fixed width


@pytest.mark.parametrize("bad_width", [0.0, -5.0, float("nan"), float("inf")])
def test_fixed_half_width_that_is_not_a_positive_number_is_rejected(bad_width):
    with pytest.raises(ValueError):
        plan_route(~TOP_TARGET, TOP_TARGET, 0.0, 0.3, fixed_half_width_px=bad_width)


# ---------------------------------------------------------------- C4: the final check has the last word

def _line_through_the_obstacle(*_args, **_kwargs) -> np.ndarray:
    return np.array([[156.0, 236.0], [156.0, 124.0]])  # straight up the middle, across OBSTACLE


def test_smoothing_that_breaks_a_rule_falls_back_to_the_plain_grid_route(monkeypatch):
    free = _scene(OBSTACLE)
    monkeypatch.setattr("vision.floor_route._smooth", _line_through_the_obstacle)

    route = plan_route(free, TARGET, HORIZON, GAIN)

    assert route is not None and len(route.points) > 2  # the cell-by-cell route, not the bad straight line
    assert not _on(OBSTACLE, _dense(route.points)).any()
    assert route_violations(route.points, route.half_width_px, free, TARGET) == []


def test_nothing_is_returned_when_every_candidate_route_breaks_a_rule(monkeypatch):
    monkeypatch.setattr("vision.floor_route._smooth", _line_through_the_obstacle)
    monkeypatch.setattr("vision.floor_route._join", _line_through_the_obstacle)

    assert plan_route(_scene(OBSTACLE), TARGET, HORIZON, GAIN) is None


def test_route_violations_with_an_empty_target_mask_reports_c3():
    points, widths = _line((160, 239), (160, 124))

    assert _broken(route_violations(points, widths, _scene(), NOTHING)) >= {"C3"}


def test_bad_mask_and_polygon_shapes_are_rejected_with_a_clear_error():
    with pytest.raises(ValueError):
        free_floor(np.ones(SHAPE, dtype=bool), np.ones((10, 10), dtype=bool), NOTHING)
    with pytest.raises(ValueError):
        polygons_to_mask([np.array([1.0, 2.0, 3.0])], SHAPE)
