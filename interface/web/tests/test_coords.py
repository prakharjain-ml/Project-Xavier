"""Coordinate contract tests (interface/web/coords.py): letterboxing, aspect ratios, zoom and fullscreen rules."""

import pytest

from interface.web.coords import Layout, contain_rect, frame_to_viewport, geometry_changed, viewport_to_frame


def layout(video, vw=1470, vh=956, dpr=2.0, fullscreen=True, sw=1470, sh=956) -> Layout:
    return Layout(vw, vh, sw, sh, dpr, fullscreen, video)


@pytest.mark.parametrize("box,frame,expected", [
    ((0, 0, 1280, 720), (1280, 720), (0, 0, 1280, 720)),          # same aspect: fills the box
    ((0, 0, 1000, 1000), (1280, 720), (0, 218.75, 1000, 562.5)),  # wide picture in a square: bars top and bottom
    ((0, 0, 1000, 400), (640, 480), (233.33, 0, 533.33, 400)),    # 4:3 picture in a wide box: bars left and right
])
def test_contain_rect_letterboxes_like_object_fit_contain(box, frame, expected):
    assert contain_rect(box, *frame) == pytest.approx(expected, abs=0.01)


def test_gaze_on_a_letterbox_bar_is_on_no_object():
    # Arrange: 16:9 picture in a square element -> bars above and below
    lay = layout((0, 0, 956, 956), vw=956, vh=956)

    # Act / Assert: the top bar is not clamped onto the picture's edge
    assert viewport_to_frame((0.5, 0.05), lay, 1280, 720) is None
    assert viewport_to_frame((0.5, 0.5), lay, 1280, 720) == pytest.approx((0.5, 0.5))


@pytest.mark.parametrize("frame", [(1280, 720), (640, 480), (1920, 1080), (720, 1280)])
def test_frame_to_viewport_and_back_round_trips(frame):
    # Arrange
    lay = layout((40, 60, 1100, 800))

    # Act
    back = viewport_to_frame(frame_to_viewport((0.3, 0.7), lay, *frame), lay, *frame)

    # Assert
    assert back == pytest.approx((0.3, 0.7))


def test_zoom_screen_change_or_leaving_fullscreen_invalidates_calibration_but_panel_resize_does_not():
    # Arrange
    calibrated = layout((0, 0, 1100, 800), dpr=2.0)

    # Act / Assert
    assert not geometry_changed(calibrated, layout((0, 0, 900, 700), dpr=2.0))   # side panel resized: still valid
    assert geometry_changed(calibrated, layout((0, 0, 1100, 800), dpr=1.0))      # zoom / other display
    assert geometry_changed(calibrated, layout((0, 0, 1100, 800), fullscreen=False))
    assert geometry_changed(calibrated, layout((0, 0, 1100, 800), sw=1920, sh=1080, vw=1920, vh=1080))
    assert geometry_changed(None, calibrated)
