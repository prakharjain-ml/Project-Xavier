"""HUD drawing tests (docs/ROUTE_REQUIREMENTS.md, "vision/hud.py"): sizes, untouched inputs, and that each part
of the look really changes pixels where it should. Everything is drawn into arrays; no window is opened."""

from dataclasses import replace

import numpy as np
import pytest

from vision import hud

FRAME_H, FRAME_W = 360, 640
GREY = 90  # flat mid-grey camera frame: any overlay shows up as a change from this value


@pytest.fixture
def frame() -> np.ndarray:
    return np.full((FRAME_H, FRAME_W, 3), GREY, np.uint8)


@pytest.fixture
def route() -> tuple[np.ndarray, np.ndarray]:
    """Straight route up the middle of the floor: bottom edge -> (320, 200), narrower with distance."""
    rows = np.linspace(FRAME_H - 1, 200, 20)
    points = np.stack([np.full_like(rows, 320.0), rows], axis=1)
    return points, np.linspace(40.0, 12.0, len(rows))


def blob(selected: bool = False, progress: float = 0.0, outline: bool = True) -> hud.SceneObject:
    """A 120 x 100 object at the left of the frame, as an eight-sided outline or as a bare box."""
    shape = np.array([(110, 80), (190, 80), (220, 110), (220, 150), (190, 180), (110, 180), (100, 150), (100, 110)],
                     float)
    return hud.SceneObject("chair", (100.0, 80.0, 220.0, 180.0), shape if outline else None, selected, progress)


def camera_area(image: np.ndarray) -> np.ndarray:
    x, y = hud.frame_origin()
    return image[y:y + FRAME_H, x:x + FRAME_W]


def changed(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Boolean (height, width) mask of the pixels that differ between two images."""
    return (a != b).any(axis=2)


def is_red(pixels: np.ndarray) -> np.ndarray:
    blue, green, red = (pixels[..., k].astype(int) for k in range(3))
    return (red > 180) & (green < 90) & (blue < 90)


def is_bright_cyan(pixels: np.ndarray) -> np.ndarray:
    """The full-strength line colour; the dimmer cyan of an unverified route does not count."""
    blue, green, red = (pixels[..., k].astype(int) for k in range(3))
    return (blue > 200) & (green > 200) & (red < 110)


def test_render_adds_a_bar_above_and_below_the_camera_frame(frame):
    # Act
    out = hud.render(frame, hud.HudState())
    x, y = hud.frame_origin()

    # Assert
    assert out.dtype == np.uint8
    assert out.shape == (hud.TOP_BAR_H + FRAME_H + hud.BOTTOM_BAR_H, FRAME_W, 3)
    assert (x, y) == (0, hud.TOP_BAR_H)


def test_empty_state_shows_the_camera_frame_unchanged_between_the_bars(frame):
    # Act
    out = hud.render(frame, hud.HudState())

    # Assert
    assert (camera_area(out) == frame).all()
    assert (out[:hud.TOP_BAR_H] != GREY).any() and (out[hud.TOP_BAR_H + FRAME_H:] != GREY).any()


def test_render_leaves_the_input_frame_and_route_untouched(frame, route):
    # Arrange
    points, half = route
    frame_before, points_before, half_before = frame.copy(), points.copy(), half.copy()
    state = hud.HudState(objects=(blob(selected=True, progress=0.5),), cursor=(300.0, 150.0), route_points=points,
                         route_half_width=half)

    # Act
    out = hud.render(frame, state)

    # Assert
    assert (frame == frame_before).all()
    assert (points == points_before).all() and (half == half_before).all()
    assert not np.shares_memory(out, frame)


def test_route_changes_pixels_along_the_floor(frame, route):
    # Arrange
    points, half = route
    plain = hud.render(frame, hud.HudState())

    # Act
    with_route = hud.render(frame, hud.HudState(route_points=points, route_half_width=half))

    # Assert: the ribbon is drawn around x = 320 from the bottom edge up to the stop ring, and nowhere else
    diff = changed(camera_area(with_route), camera_area(plain))
    assert diff[210:FRAME_H, 270:370].mean() > 0.3
    assert not diff[:150].any() and not diff[:, :200].any() and not diff[:, 440:].any()


def test_no_route_leaves_the_camera_area_equal_to_a_render_without_one(frame, route):
    # Arrange
    _, half = route
    base = hud.HudState(objects=(blob(),))

    # Act
    plain = hud.render(frame, base)
    no_route = hud.render(frame, replace(base, route_points=None, route_half_width=half, route_verified=False))

    # Assert
    assert (camera_area(no_route) == camera_area(plain)).all()


def test_route_with_a_nan_point_is_not_drawn(frame, route):
    # Arrange: a broken route must never be shown as if it were a route (C4)
    points, half = route
    broken = points.copy()
    broken[3, 0] = np.nan

    # Act
    out = hud.render(frame, hud.HudState(route_points=broken, route_half_width=half))

    # Assert
    assert (camera_area(out) == frame).all()


def test_route_without_matching_half_widths_is_rejected(frame, route):
    points, half = route
    with pytest.raises(ValueError):
        hud.render(frame, hud.HudState(route_points=points, route_half_width=half[:-1]))
    with pytest.raises(ValueError):
        hud.render(frame, hud.HudState(route_points=points, route_half_width=None))


def test_unverified_route_is_dashed_dimmer_and_unfilled(frame, route):
    # Arrange
    points, half = route
    state = hud.HudState(route_points=points, route_half_width=half)
    plain = camera_area(hud.render(frame, hud.HudState()))

    # Act
    checked = camera_area(hud.render(frame, state))
    unverified = camera_area(hud.render(frame, replace(state, route_verified=False)))

    # Assert: both draw something, they differ, and the unverified one covers far less and has no bright cyan
    drawn_checked, drawn_unverified = changed(checked, plain), changed(unverified, plain)
    assert drawn_unverified.any() and changed(checked, unverified).any()
    assert drawn_unverified.sum() < 0.5 * drawn_checked.sum()
    assert is_bright_cyan(checked).any() and not is_bright_cyan(unverified).any()
    # Between the edges and between two chevrons the checked ribbon is filled, the unverified one is not.
    inside = (slice(300, 304), slice(300, 304))
    assert drawn_checked[inside].all() and not drawn_unverified[inside].any()


def test_phase_moves_the_chevrons_and_repeats_after_one_full_step(frame, route):
    # Arrange
    points, half = route
    state = hud.HudState(route_points=points, route_half_width=half)

    # Act
    start = hud.render(frame, state)
    moved = hud.render(frame, replace(state, phase=0.5))
    wrapped = hud.render(frame, replace(state, phase=1.0))

    # Assert
    assert changed(start, moved).any()
    assert (start == wrapped).all()


def test_chevrons_move_toward_the_target_as_phase_grows(route):
    # Arrange: the route runs straight up the image, so "toward the target" means a smaller row number
    points, half = route
    ribbon = hud._build_ribbon(hud.HudState(route_points=points, route_half_width=half), FRAME_H, FRAME_W)

    # Act
    before = hud._chevrons(ribbon, 0.2)
    after = hud._chevrons(ribbon, 0.4)

    # Assert
    assert len(before) >= 3 and len(after) >= 3
    assert all(later[:, 1].mean() < earlier[:, 1].mean() for earlier, later in zip(before, after))
    widths = [np.ptp(shape[:, 0]) for shape in before]
    assert widths == sorted(widths, reverse=True)  # biggest next to the chair, smaller toward the target


def test_selected_object_is_filled_and_differs_from_unselected(frame):
    # Act
    unselected = camera_area(hud.render(frame, hud.HudState(objects=(blob(),))))
    selected = camera_area(hud.render(frame, hud.HudState(objects=(blob(selected=True),))))

    # Assert: unselected = thin outline only (its inside is untouched); selected = inside tinted toward cyan
    inside = (slice(150, 170), slice(120, 200))
    assert (unselected != frame).any()
    assert (unselected[inside] == GREY).all()
    assert (selected[inside][..., 0] > selected[inside][..., 2]).all()  # more blue than red
    assert changed(selected, unselected).sum() > 2 * changed(unselected, frame).sum()


def test_reticle_arc_grows_with_confirm_progress(frame):
    # Act
    idle = hud.render(frame, hud.HudState(objects=(blob(selected=True, progress=0.0),)))
    half = hud.render(frame, hud.HudState(objects=(blob(selected=True, progress=0.5),)))
    full = hud.render(frame, hud.HudState(objects=(blob(selected=True, progress=1.0),)))

    # Assert: the thicker arc covers more pixels the further the confirm has got
    assert 0 < changed(idle, half).sum() < changed(idle, full).sum()


def test_object_without_outline_falls_back_to_corner_brackets(frame):
    # Act
    out = camera_area(hud.render(frame, hud.HudState(objects=(blob(outline=False),))))

    # Assert: the four corners of the box are drawn, the middle of each side and the inside are not
    diff = changed(out, frame)
    for corner_x, corner_y in ((100, 80), (220, 80), (100, 180), (220, 180)):
        assert diff[corner_y - 2:corner_y + 3, corner_x - 2:corner_x + 3].any()
    assert not diff[76:85, 150:170].any() and not diff[120:140, 96:105].any()
    assert not diff[100:160, 120:200].any()


def test_cursor_is_drawn_where_asked_and_nowhere_else(frame):
    # Act
    out = camera_area(hud.render(frame, hud.HudState(cursor=(400.0, 120.0))))

    # Assert
    diff = changed(out, frame)
    rows, cols = np.nonzero(diff)
    assert diff[120, 400]
    assert abs(rows.mean() - 120) < 1.5 and abs(cols.mean() - 400) < 1.5
    assert rows.min() > 70 and rows.max() < 170 and cols.min() > 350 and cols.max() < 450
    assert is_bright_cyan(out[100:140, 380:420]).any()


def test_stop_button_lies_inside_the_bottom_bar_and_is_red(frame):
    # Act
    out = hud.render(frame, hud.HudState())
    x1, y1, x2, y2 = hud.stop_button_rect(FRAME_W, FRAME_H)

    # Assert
    bar_top = hud.frame_origin()[1] + FRAME_H
    assert 0 <= x1 < x2 <= FRAME_W
    assert bar_top <= y1 < y2 <= out.shape[0]
    assert is_red(out[y1:y2, x1:x2]).mean() > 0.5
    assert not is_red(np.delete(out, np.s_[x1:x2], axis=1)).any()  # red appears only inside the rectangle


@pytest.mark.parametrize("width", [40, 160, 320])
def test_stop_button_stays_visible_on_a_narrow_frame_with_long_text(width):
    # Arrange: text far too long for the bar must never cover the button (C9)
    frame = np.full((120, width, 3), GREY, np.uint8)
    state = hud.HudState(mode="A very long mode name " * 5, status="An even longer status line " * 8)

    # Act
    out = hud.render(frame, state)
    x1, y1, x2, y2 = hud.stop_button_rect(width, 120)

    # Assert
    assert 0 <= x1 < x2 <= width and y2 <= out.shape[0]
    assert is_red(out[y1:y2, x1:x2]).mean() > 0.4


def test_title_is_xavier_by_default_and_bars_follow_the_state_text(frame):
    # Act
    default = hud.render(frame, hud.HudState())
    other_title = hud.render(frame, hud.HudState(title_left="OTHER"))
    other_status = hud.render(frame, hud.HudState(status="Moving"))

    # Assert
    assert hud.HudState().title_left == "XAVIER"
    assert changed(default[:hud.TOP_BAR_H], other_title[:hud.TOP_BAR_H]).any()
    assert changed(default[hud.TOP_BAR_H + FRAME_H:], other_status[hud.TOP_BAR_H + FRAME_H:]).any()
    assert (camera_area(default) == camera_area(other_status)).all()


def test_selected_object_at_the_frame_edge_keeps_its_label_inside_the_frame(frame):
    # Arrange: an object in the top-right corner, where the label pill would otherwise leave the frame
    corner = hud.SceneObject("potted plant", (560.0, 2.0, 638.0, 70.0), None, selected=True, progress=0.4)

    # Act
    out = hud.render(frame, hud.HudState(objects=(corner,)))

    # Assert
    assert out.shape[1] == FRAME_W and (camera_area(out) != frame).any()


def test_everything_at_once_renders_on_a_tiny_frame():
    # Arrange
    tiny = np.zeros((24, 32, 3), np.uint8)
    state = hud.HudState(objects=(hud.SceneObject("cup", (4.0, 4.0, 20.0, 18.0), None, True, 0.5),),
                         cursor=(10.0, 10.0), route_points=np.array([(16.0, 23.0), (16.0, 2.0)]),
                         route_half_width=np.array([6.0, 2.0]))

    # Act
    out = hud.render(tiny, state)

    # Assert
    assert out.shape == (hud.TOP_BAR_H + 24 + hud.BOTTOM_BAR_H, 32, 3)


def test_render_rejects_a_frame_that_is_not_a_colour_image():
    with pytest.raises(ValueError):
        hud.render(np.zeros((FRAME_H, FRAME_W), np.uint8), hud.HudState())
    with pytest.raises(ValueError):
        hud.render(np.zeros((FRAME_H, FRAME_W, 3), np.float32), hud.HudState())


def test_missing_font_files_fall_back_without_crashing(frame, monkeypatch):
    # Arrange: point every face at a file that does not exist, and forget anything drawn with the real fonts
    monkeypatch.setattr(hud, "FONT_FILES", {face: ("/no/such/font.ttf", 0) for face in hud.FONT_FILES})
    hud.clear_caches()
    state = hud.HudState(objects=(blob(selected=True, progress=0.3),))

    try:
        # Act
        out = hud.render(frame, state)
        x1, y1, x2, y2 = hud.stop_button_rect(FRAME_W, FRAME_H)

        # Assert: bars, label and STOP are all still drawn
        assert out.shape == (hud.TOP_BAR_H + FRAME_H + hud.BOTTOM_BAR_H, FRAME_W, 3)
        assert (out[:hud.TOP_BAR_H].max(axis=2) > 200).any()  # white title text
        assert is_red(out[y1:y2, x1:x2]).mean() > 0.5
    finally:
        hud.clear_caches()  # the next test must not get bars drawn with the fallback font
