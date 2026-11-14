"""Floor point (metres) -> image pixel (vision/floor.py)."""

import numpy as np
import pytest

from vision.floor import project_floor

W, H, HFOV = 1280, 720, 85.5


def test_point_straight_ahead_is_on_the_centre_column_and_farther_is_higher():
    px = project_floor(np.array([[1.0, 0.0], [3.0, 0.0]]), W, H, HFOV, cam_height_m=1.0, pitch_deg=15)
    assert px[0][0] == pytest.approx(W / 2, abs=1) and px[1][0] == pytest.approx(W / 2, abs=1)
    assert px[1][1] < px[0][1]  # farther along the floor = higher in the image


def test_left_of_the_chair_is_left_in_the_image():
    px = project_floor(np.array([[2.0, 0.5]]), W, H, HFOV, 1.0, 15)
    assert px[0][0] < W / 2


def test_points_behind_or_beyond_the_horizon_are_nan():
    px = project_floor(np.array([[-1.0, 0.0]]), W, H, HFOV, 1.0, 0)
    assert np.isnan(px).all()
