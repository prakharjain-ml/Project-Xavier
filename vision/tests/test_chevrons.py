"""Chevron placement along a route (vision/chevrons.py). Geometry only, no drawing."""

import math

import numpy as np
import pytest

from vision.chevrons import GUIDE_COUNT, place_guides, project_points, route_length_m
from vision.floor import project_floor

W, H, HFOV, CAM_H, PITCH = 1280, 720, 85.5, 0.89, 15.0


def guides_for(route):
    return place_guides(np.array(route, float), W, H, HFOV, CAM_H, PITCH)


def test_height_zero_matches_the_floor_projection():
    floor = np.array([[2.0, 0.3], [3.5, -0.8]])
    pixels, _ = project_points(np.c_[floor, np.zeros(2)], W, H, HFOV, CAM_H, PITCH)
    assert np.allclose(pixels, project_floor(floor, W, H, HFOV, CAM_H, PITCH))


def test_straight_route_gives_upright_chevrons_that_shrink_with_distance():
    guides = guides_for([[1.2, 0.0], [4.0, 0.0]])
    assert 2 <= len(guides) <= GUIDE_COUNT
    assert all(abs(g.angle) < math.radians(3) for g in guides)  # pointing straight ahead
    assert all(abs(g.center[0] - W / 2) < 2 for g in guides)  # in the middle of the picture
    sizes = [g.size for g in guides]
    assert sizes == sorted(sizes, reverse=True)  # nearer = bigger
    assert [g.order for g in guides] == list(range(len(guides)))


def test_route_bending_left_tilts_the_chevrons_to_the_left_and_right_to_the_right():
    left = guides_for([[1.2, 0.0], [2.0, 0.4], [2.6, 1.6]])
    right = guides_for([[1.2, 0.0], [2.0, -0.4], [2.6, -1.6]])
    assert max(g.angle for g in left) > math.radians(20)
    assert min(g.angle for g in right) < -math.radians(20)
    assert left[-1].angle == pytest.approx(-right[-1].angle, abs=1e-6)  # mirror images


def test_no_chevron_in_the_last_stretch_before_the_stop_point():
    guides = guides_for([[1.2, 0.0], [1.5, 0.0]])  # 1.5 m route: first slot at 1.35 m, end clear from 1.25 m
    assert guides == ()


def test_no_route_or_a_broken_route_gives_no_chevrons():
    assert place_guides(None, W, H, HFOV, CAM_H, PITCH) == ()
    assert guides_for(np.zeros((0, 2))) == ()
    assert guides_for([[1.0, float("nan")]]) == ()


def test_route_length_counts_the_unseen_first_leg_from_the_chair():
    assert route_length_m(np.array([[1.0, 0.0], [1.0, 2.0]])) == pytest.approx(3.0)


def test_hud_draws_the_chevrons_and_label_without_touching_the_input_frame():
    from vision import hud

    frame = np.full((H, W, 3), 90, np.uint8)
    before = frame.copy()
    guides = guides_for([[1.2, 0.0], [2.0, 0.4], [2.6, 1.6]])
    plain = hud.render(frame, hud.HudState())
    drawn = hud.render(frame, hud.HudState(guides=guides, guide_label="Toward chair · 2.4 m", clock=1.0))
    assert np.array_equal(frame, before)
    assert (np.abs(drawn.astype(int) - plain.astype(int)).sum(axis=2) > 60).sum() > 2000  # clearly drawn
