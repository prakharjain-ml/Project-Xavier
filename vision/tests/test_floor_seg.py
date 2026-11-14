"""Colour-based floor finder (vision/floor_seg.py). Synthetic pictures only."""

import numpy as np

from vision.floor_seg import colour_floor

GREY, WHITE, BROWN = (110, 110, 110), (235, 235, 235), (60, 100, 150)


def room():
    """White wall on top, grey floor below row 200, a brown box standing on the floor."""
    img = np.full((360, 640, 3), WHITE, np.uint8)
    img[200:] = GREY
    img[240:300, 400:480] = BROWN
    return img


def test_floor_is_the_grey_area_but_not_the_wall_or_the_box():
    floor = colour_floor(room(), np.zeros((360, 640), bool), horizon_row=100.0)
    assert floor[340, 100] and floor[220, 100]  # near and far floor
    assert not floor[150, 100]  # the wall is below the horizon but is not floor-coloured
    assert not floor[270, 440]  # the box standing on the floor


def test_nothing_at_or_above_the_horizon_is_floor_even_if_it_has_the_floor_colour():
    img = np.full((360, 640, 3), GREY, np.uint8)  # floor colour everywhere
    floor = colour_floor(img, np.zeros((360, 640), bool), horizon_row=180.0)
    assert floor[300, 320] and not floor[100, 320]


def test_floor_colour_behind_a_wall_is_not_floor_because_it_is_not_connected():
    img = room()
    img[120:160, 200:300] = GREY  # a grey picture on the white wall
    floor = colour_floor(img, np.zeros((360, 640), bool), horizon_row=50.0)
    assert not floor[140, 250]


def test_detected_objects_are_never_floor_and_the_inputs_are_left_alone():
    img, objects = room(), np.zeros((360, 640), bool)
    objects[250:360, 100:200] = True  # a detected chair, the same colour as the floor
    before_img, before_objects = img.copy(), objects.copy()
    floor = colour_floor(img, objects, horizon_row=100.0)
    assert not floor[300, 150] and floor[300, 300]
    assert np.array_equal(img, before_img) and np.array_equal(objects, before_objects)


def test_floor_that_gets_darker_with_distance_is_still_floor():
    img = room()
    shade = np.linspace(0.75, 1.0, 160)[:, None, None]  # far floor 25% darker than near floor
    img[200:] = (np.array(GREY) * shade).astype(np.uint8)
    floor = colour_floor(img, np.zeros((360, 640), bool), horizon_row=100.0)
    assert floor[210, 100] and floor[350, 100]


def test_no_floor_at_all_when_objects_cover_the_bottom_of_the_view():
    objects = np.zeros((360, 640), bool)
    objects[300:] = True
    assert not colour_floor(room(), objects, horizon_row=100.0).any()
