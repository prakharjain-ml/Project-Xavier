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


def test_stop_point_is_arrive_distance_short_of_the_object():
    import math

    from control.navigation import ARRIVE_M
    from vision.nav_preview import stop_point

    x, y = stop_point((3.0, 0.0))
    assert (x, y) == (3.0 - ARRIVE_M, 0.0)
    assert stop_point((0.3, 0.0)) == (0.0, 0.0)  # already inside the arrival distance: stay put
    sx, sy = stop_point((2.0, 2.0))
    assert math.isclose(math.hypot(2.0 - sx, 2.0 - sy), ARRIVE_M)


def test_path_clearance_is_the_closest_approach():
    import numpy as np

    from vision.nav_preview import path_clearance

    path = [(0.0, 0.0), (2.0, 0.0)]
    assert path_clearance(path, np.array([[1.0, 0.5]])) == pytest.approx(0.5, abs=0.02)
    assert path_clearance(path, np.zeros((0, 2))) is None
    assert path_clearance(None, np.array([[1.0, 0.5]])) is None


def test_compose_draws_the_floor_path_and_panel_without_a_window():
    import cv2
    import numpy as np

    from control.goto import NavState
    from control.navigation import NavConfig
    from vision.detect_track import Track
    from vision.nav_preview import PANEL_W, compose

    frame = np.zeros((720, 1280, 3), np.uint8)
    chair = Track(id=4, label="chair", conf=0.9, bbox=(560, 200, 720, 520), distance_m=3.0)
    person = Track(id=7, label="person", conf=0.9, bbox=(300, 150, 420, 600), distance_m=1.8)
    out = compose(cv2, frame, [chair, person], chair, NavState(0.3, 0.1), (80, 90), False, 85.5, 1.0, 15.0, 30.0,
                  NavConfig())
    assert out.shape == (720, 1280 + PANEL_W, 3)
    assert out[400:720, 400:880].max() > 150  # the bright ribbon is on the floor ahead of the chair
    empty = compose(cv2, frame, [], None, NavState(), (0, 0), False, 85.5, 1.0, 15.0, 30.0, NavConfig())
    assert empty.shape == out.shape and not frame.any()  # no target still renders; the input is untouched
