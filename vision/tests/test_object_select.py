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


def test_dwell_carries_over_when_the_tracker_relabels_the_same_object():
    box = (0.1, 0.1, 0.4, 0.5)
    sel = update_selection(Selection(), hit=84, now=0.0, box=box)
    nudged = (0.11, 0.1, 0.41, 0.5)  # same chair, new ID from the tracker
    sel = update_selection(sel, hit=130, now=1.0, box=nudged)
    assert sel.candidate == 130 and sel.since == 0.0  # dwell kept running
    sel = update_selection(sel, hit=130, now=DWELL_S + 0.01, box=nudged)
    assert sel.confirmed == 130


def test_a_different_object_elsewhere_still_restarts_the_dwell():
    sel = update_selection(Selection(), hit=84, now=0.0, box=(0.1, 0.1, 0.4, 0.5))
    sel = update_selection(sel, hit=130, now=1.0, box=(0.6, 0.1, 0.9, 0.5))  # no overlap: really another object
    assert sel.since == 1.0


def test_gaze_problem_names_the_reason():
    from vision.object_select import gaze_problem

    assert gaze_problem(None, now=1.0) == "no_sample"
    assert gaze_problem(GazeSample((0.5, 0.5), False, True, 0.0), now=5.0) == "stale"
    assert gaze_problem(GazeSample(None, False, False, 1.0), now=1.0) == "no_face"
    assert gaze_problem(GazeSample(None, True, True, 1.0), now=1.0) == "eyes_closed"
    assert gaze_problem(GazeSample((0.5, 0.5), False, True, 1.0), now=1.0) is None


def test_session_ends_at_once_if_the_eye_tracker_dies():
    import queue
    import time

    from vision.object_select import run

    class FakeCv2:
        def waitKey(self, _ms):  # noqa: N802 - OpenCV's name
            return 255

        def imshow(self, *_args):
            pass

    class NoFrames:
        def latest(self):
            return None

    start = time.monotonic()
    result = run(FakeCv2(), NoFrames(), model=None, classes=None, gaze_queue=queue.Queue(), hfov=70.0,
                 device="cpu", seconds=5.0, tracker_alive=lambda: False)
    assert result == [] and time.monotonic() - start < 1.0  # did not sit there for the full 5 s


def test_confirm_event_needs_a_short_look_first():
    from vision.object_select import MIN_LOOK_S

    sel = update_selection(Selection(), hit=7, now=0.0, dwell_s=None)
    sel = update_selection(sel, hit=7, now=MIN_LOOK_S / 2, dwell_s=None, confirm=True)
    assert sel.confirmed is None  # clench while the eyes are still arriving: ignored
    sel = update_selection(sel, hit=7, now=MIN_LOOK_S + 0.01, dwell_s=None, confirm=True)
    assert sel.confirmed == 7


def test_confirm_mode_never_confirms_by_dwell_alone():
    sel = update_selection(Selection(), hit=7, now=0.0, dwell_s=None)
    sel = update_selection(sel, hit=7, now=10.0, dwell_s=None)
    assert sel.confirmed is None  # looking for 10 s without a clench does nothing


def test_confirm_event_with_nothing_under_the_gaze_does_nothing():
    sel = update_selection(Selection(), hit=None, now=1.0, dwell_s=None, confirm=True)
    assert sel.confirmed is None
