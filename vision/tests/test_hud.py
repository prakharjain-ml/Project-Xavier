"""HUD drawing smoke tests: right shapes, pixels change, inputs untouched (no window opened)."""

import numpy as np

from vision.floor import project_floor
from vision.hud import TextLayer, corner_box, draw_floor_path, draw_ground_ring, side_panel


def project(points):
    return project_floor(points, 1280, 720, 85.5, 1.0, 15)


def test_floor_path_draws_without_touching_the_input():
    img = np.zeros((720, 1280, 3), np.uint8)
    out = draw_floor_path(img, [(0.0, 0.0), (1.5, 0.4), (3.0, 0.0)], project)
    assert out.shape == img.shape and out.any() and not img.any()


def test_ring_box_text_and_panel_render():
    img = np.zeros((720, 1280, 3), np.uint8)
    assert draw_ground_ring(img, (3.0, 0.0), project).any()
    assert corner_box(img, (100, 100, 400, 500), "#cbe9fd", glow=True).any()
    layer = TextLayer()
    layer.add("chair 2.1 m", (120, 90), 28)
    assert layer.render(img).any()
    panel = side_panel(720, 420, {"sections": [("target", "chair")], "command": "FORWARD", "left": 80, "right": -40})
    assert panel.shape == (720, 420, 3)


def test_no_path_means_unchanged_image():
    img = np.full((10, 10, 3), 7, np.uint8)
    assert (draw_floor_path(img, None, project) == img).all()
