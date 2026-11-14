import pytest

from vision.nav_preview import direction_label


@pytest.mark.parametrize("left, right, label", [
    (0, 0, "STOP"),
    (100, 100, "FORWARD"),
    (100, 70, "FORWARD + RIGHT"),
    (70, 100, "FORWARD + LEFT"),
    (60, -60, "SPIN RIGHT"),
    (-60, 60, "SPIN LEFT"),
    (3, -2, "STOP"),  # tiny speeds below the board's dead zone count as stopped
])
def test_direction_label(left, right, label):
    assert direction_label(left, right) == label


SHAPE = (360, 640)  # small frame so the planner tests run fast
HORIZON = 119.0  # image row of the horizon for the test camera below (0.89 m high, tilted 10 degrees down)


def make_view():
    from vision.route_scene import floor_view

    return floor_view(SHAPE[1], SHAPE[0], 85.5, 0.89, 10.0)


def make_track(tid, bbox, label="chair", outline=None):
    from vision.detect_track import Track

    return Track(tid, label, 0.9, bbox, 2.0, outline)


def make_advice(floor, no_go=(), route=None, target_id=1):
    import numpy as np

    from vision.scene_ai import SceneAdvice

    return SceneAdvice(floor=tuple(floor), no_go=tuple(no_go), route=np.zeros((0, 2)) if route is None else route,
                       target_id=target_id, frame_t=0.0, thumb=np.zeros((9, 16), np.uint8), model="fake",
                       latency_s=0.0)


def whole_floor():
    import numpy as np

    return np.array([[0, HORIZON + 5], [SHAPE[1] - 1, HORIZON + 5], [SHAPE[1] - 1, SHAPE[0] - 1], [0, SHAPE[0] - 1]],
                    np.float32)


def test_track_mask_uses_the_outline_when_there_is_one_and_the_box_otherwise():
    import numpy as np

    from vision.route_scene import track_mask

    triangle = np.array([[100, 100], [200, 100], [100, 200]], np.float32)
    outlined = track_mask(make_track(1, (100, 100, 200, 200), outline=triangle), SHAPE)
    boxed = track_mask(make_track(1, (100, 100, 200, 200)), SHAPE)
    assert outlined[110, 110] and not outlined[190, 190]  # the far corner of the box is outside the triangle
    assert boxed[190, 190] and boxed.sum() > outlined.sum()


def test_cursor_picks_the_smallest_object_under_it():
    from vision.route_scene import cursor_hit

    table, vase = make_track(1, (100, 100, 400, 300), "dining table"), make_track(2, (200, 150, 240, 200), "vase")
    assert cursor_hit([table, vase], (220, 170)) == 2  # on both: the vase wins
    assert cursor_hit([table, vase], (120, 120)) == 1
    assert cursor_hit([table, vase], (500, 50)) is None and cursor_hit([table, vase], None) is None


def test_route_without_gemini_is_marked_unverified():
    from vision.route_scene import plan

    target = make_track(1, (280, 130, 360, 200))
    route, verified = plan(SHAPE, [target], target, None, make_view())
    assert route is not None and verified is False


def test_route_on_gemini_floor_is_verified_and_stays_off_detected_objects():
    from vision.route_scene import plan, track_mask

    target, blocker = make_track(1, (280, 130, 360, 200)), make_track(2, (200, 230, 440, 270), "couch")
    advice = make_advice([whole_floor()])  # Gemini wrongly calls everything floor, including under the couch
    route, verified = plan(SHAPE, [target, blocker], target, advice, make_view())
    assert route is not None and verified is True
    couch = track_mask(blocker, SHAPE)
    assert not any(couch[int(y), int(x)] for x, y in route.points)  # the detector's object wins (C5)


def test_gemini_no_go_blocks_the_route_but_its_shape_around_the_target_is_ignored():
    import numpy as np

    from vision.route_scene import plan

    target = make_track(1, (280, 130, 360, 200))
    around_target = np.array([[260, 110], [380, 110], [380, 240], [260, 240]], np.float32)
    wall = np.array([[0, 215], [639, 215], [639, 250], [0, 250]], np.float32)  # a band right across the floor
    open_route, _ = plan(SHAPE, [target], target, make_advice([whole_floor()], [("armchair", around_target)]),
                         make_view())
    blocked, _ = plan(SHAPE, [target], target, make_advice([whole_floor()], [("glass wall", wall)]),
                      make_view())
    assert open_route is not None  # Gemini's rough shape around the target must not hide the floor in front of it
    assert blocked is None  # nothing gets through a no-go band: no route, not a guess (C4)


def test_status_line_says_where_the_floor_came_from():
    import numpy as np

    from vision.floor_route import Route
    from vision.nav_preview import status_line

    target = make_track(1, (280, 100, 360, 160))
    route = Route(points=np.zeros((2, 2)), half_width_px=np.ones(2), via_gemini=False)
    assert "Rest the cursor" in status_line(None, None, False, "off")
    assert "No safe route" in status_line(target, None, True, "ready")
    assert "Gemini-checked" in status_line(target, route, True, "ready")
    assert "unverified" in status_line(target, route, False, "off")
    assert "checking the floor" in status_line(target, route, False, "analysing")


def test_parse_cursor_accepts_fractions_and_rejects_anything_else():
    from vision.nav_preview import parse_cursor

    assert parse_cursor("0.8,0.6") == (0.8, 0.6) and parse_cursor(None) is None
    with pytest.raises(ValueError):
        parse_cursor("900,400")
    with pytest.raises(ValueError):
        parse_cursor("left")


def test_mouse_reports_frame_pixels_and_a_stop_click_once():
    import cv2

    from vision import hud
    from vision.nav_preview import Mouse

    mouse = Mouse()
    ox, oy = hud.frame_origin()
    mouse.on_event(cv2.EVENT_MOUSEMOVE, ox + 100, oy + 50, 0, None)
    assert mouse.cursor == (100.0, 50.0)
    mouse.on_event(cv2.EVENT_MOUSEMOVE, ox + 100, oy - 5, 0, None)  # on the top bar: not on the camera image
    assert mouse.cursor is None and not mouse.take_stop()
    x1, y1, x2, y2 = hud.stop_button_rect(*mouse.frame_size)
    mouse.on_event(cv2.EVENT_LBUTTONDOWN, (x1 + x2) // 2, (y1 + y2) // 2, 0, None)
    assert mouse.take_stop() and not mouse.take_stop()  # reported once, then cleared


def test_run_on_a_photo_renders_a_screen_without_a_window_or_motors(tmp_path):
    import cv2
    import numpy as np

    import vision.nav_preview as preview

    path = str(tmp_path / "room.png")
    cv2.imwrite(path, np.full((360, 640, 3), 120, np.uint8))
    chair = make_track(1, (600, 250, 760, 400))

    class FakeModel:
        names = {0: "chair"}

    original = preview.detect
    preview.detect = lambda *args, **kwargs: [chair]
    try:
        screen = preview.run(preview.StillImage(path), FakeModel(), None, 85.5, 2.5, 1.0, 15.0, advisor=None,
                             fixed_cursor=(0.53, 0.45), show=False)  # cursor rests on the chair for > 1.5 s
    finally:
        preview.detect = original
    assert screen is not None and screen.shape[1] == preview.VIEW_W


def test_top_view_and_back_is_the_same_floor_point():
    import numpy as np

    from vision.route_scene import image_points, top_points

    view = make_view()
    floor_pixels = np.array([[320.0, 300.0], [100.0, 250.0], [600.0, 340.0]])  # all below the horizon
    back = image_points(top_points(floor_pixels, view), view)
    assert np.allclose(back, floor_pixels, atol=0.5)
    assert len(top_points(np.array([[320.0, 50.0]]), view)) == 0  # above the horizon: not floor


def test_chair_width_in_the_top_view_is_real_metres_not_image_pixels():
    import numpy as np

    from vision.floor import project_floor
    from vision.route_scene import top_points

    view = make_view()
    # Two floor points 1 m apart sideways, 3 m ahead, and two 1 m apart in depth: both pairs must come out 1 m
    # (100 top-view pixels) apart, although in the image the depth pair is far closer together.
    metres = np.array([[3.0, 0.5], [3.0, -0.5], [2.5, 0.0], [3.5, 0.0]])
    pixels = project_floor(metres, SHAPE[1], SHAPE[0], 85.5, 0.89, 10.0)
    top = top_points(pixels, view)
    assert abs(np.linalg.norm(top[0] - top[1]) - 100) < 2 and abs(np.linalg.norm(top[2] - top[3]) - 100) < 2
    assert np.linalg.norm(pixels[2] - pixels[3]) < 0.5 * np.linalg.norm(pixels[0] - pixels[1])


def test_gemini_floor_that_stops_just_short_of_the_bottom_edge_still_gives_a_route():
    import numpy as np

    from vision.route_scene import plan, snap_to_border

    target = make_track(1, (280, 130, 360, 200))
    short = np.array([[10, HORIZON + 5], [630, HORIZON + 5], [630, 350], [10, 350]], np.float32)  # ends 10 px high
    before = short.copy()
    route, verified = plan(SHAPE, [target], target, make_advice([short]), make_view())
    assert route is not None and verified is True
    assert np.array_equal(short, before)  # the polygon passed in was not changed
    assert snap_to_border(short, SHAPE)[:, 1].max() == SHAPE[0] - 1


def test_gemini_route_hints_that_sit_on_the_target_do_not_stop_a_route_being_found():
    import numpy as np

    from vision.route_scene import plan

    target = make_track(1, (280, 130, 360, 200))
    hints = np.array([[320.0, 340.0], [320.0, 260.0], [320.0, 170.0]])  # the last hint is on the target itself
    route, _ = plan(SHAPE, [target], target, make_advice([whole_floor()], route=hints), make_view())
    assert route is not None


def test_gemini_box_around_a_detected_object_is_dropped_but_one_around_an_unknown_object_is_kept():
    import numpy as np

    from vision.route_scene import extra_no_go

    target, chair = make_track(1, (280, 130, 360, 200)), make_track(2, (100, 200, 200, 330))
    box = lambda x1, y1, x2, y2: np.array([[x1, y1], [x2, y1], [x2, y2], [x1, y2]], np.float32)  # noqa: E731
    gemini = [("chair", box(95, 190, 210, 335)), ("table", box(420, 220, 520, 300)), ("armchair", box(270, 120, 370, 210))]
    kept = extra_no_go(gemini, [target, chair], target)
    assert len(kept) == 1 and kept[0][0, 0] == 420  # only the table, which the detector did not find
