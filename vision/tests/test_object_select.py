"""Gaze-on-objects selection logic (vision/object_select.py). Pure: no camera, no window."""

import pytest

from shared.protocol import DWELL_S
from vision.detect_track import Track
from vision.gaze import GazeSample
from vision.object_select import (
    MIN_HIT_SIZE,
    Selection,
    corrected_point,
    hit_boxes,
    update_selection,
)


def track(tid, bbox):
    return Track(id=tid, label="chair", conf=0.9, bbox=bbox, distance_m=2.0)


def test_dwell_on_one_object_confirms_it():
    sel = update_selection(Selection(), hit=7, now=0.0)
    assert (sel.candidate, sel.confirmed) == (7, None)
    sel = update_selection(sel, hit=7, now=DWELL_S - 0.1)
    assert sel.confirmed is None  # not yet
    sel = update_selection(sel, hit=7, now=DWELL_S + 0.01)
    assert sel.confirmed == 7


def test_looking_away_resets_the_dwell_but_keeps_a_confirmation():
    sel = update_selection(Selection(), hit=7, now=0.0)
    sel = update_selection(sel, hit=None, now=1.0)
    assert sel.candidate is None
    sel = update_selection(sel, hit=7, now=1.1)
    sel = update_selection(sel, hit=7, now=1.1 + DWELL_S - 0.1)
    assert sel.confirmed is None  # the earlier 1 s did not count: dwell restarted
    sel = update_selection(sel, hit=7, now=1.1 + DWELL_S + 0.01)
    sel = update_selection(sel, hit=None, now=5.0)
    assert sel.confirmed == 7  # looking away does not undo a confirmation (cancel key does)


def test_switching_objects_needs_a_full_new_dwell():
    sel = Selection(candidate=7, since=0.0, confirmed=7)
    sel = update_selection(sel, hit=9, now=10.0)
    assert sel.confirmed == 7 and sel.candidate == 9
    sel = update_selection(sel, hit=9, now=10.0 + DWELL_S + 0.01)
    assert sel.confirmed == 9


def test_selection_is_immutable():
    sel = Selection()
    update_selection(sel, hit=3, now=0.0)
    assert sel.candidate is None


def test_hit_boxes_are_normalized_and_small_objects_get_a_minimum_size():
    targets = [track(1, (0, 0, 960, 540)), track(2, (1800, 1000, 1810, 1010))]  # big box, tiny box
    boxes = hit_boxes(targets, frame_w=1920, frame_h=1080)
    assert boxes[1] == pytest.approx((0.0, 0.0, 0.5, 0.5))
    x1, y1, x2, y2 = boxes[2]
    assert x2 - x1 == pytest.approx(MIN_HIT_SIZE) and y2 - y1 == pytest.approx(MIN_HIT_SIZE)
    assert 0.0 <= x1 and x2 <= 1.0 and 0.0 <= y1 and y2 <= 1.0  # enlarged box stays on screen


def test_corrected_point_applies_offset_and_rejects_stale_or_missing():
    sample = GazeSample((0.4, 0.7), False, True, 10.0)
    assert corrected_point(sample, offset=(0.1, -0.2), now=10.1) == pytest.approx((0.5, 0.5))
    assert corrected_point(sample, offset=(0.0, 0.0), now=11.0) is None  # older than 0.5 s
    assert corrected_point(GazeSample(None, True, True, 10.0), offset=(0.0, 0.0), now=10.0) is None
    assert corrected_point(None, offset=(0.0, 0.0), now=10.0) is None
