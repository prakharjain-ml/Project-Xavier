"""Tests for the pure parts of vision/detect_track.py (no model, no camera)."""

import pytest

from vision.detect_track import (
    TARGET_FREQS_HZ,
    Track,
    assign_frequencies,
    estimate_distance_m,
    focal_length_px,
    pick_targets,
    steering_offset,
)


def track(tid, label="person", h=200, x1=100, conf=0.9):
    return Track(id=tid, label=label, conf=conf, bbox=(x1, 100, x1 + 80, 100 + h), distance_m=None)


def test_focal_length_from_field_of_view():
    # 90 degree view: half the width sits at 45 degrees, tan(45) = 1, so f = width / 2.
    assert focal_length_px(1280, 90.0) == pytest.approx(640.0)


def test_distance_halves_when_box_doubles():
    far = estimate_distance_m("person", 100, focal_px=1000)
    near = estimate_distance_m("person", 200, focal_px=1000)
    assert far == pytest.approx(17.0)  # 1.7 m * 1000 px / 100 px
    assert near == pytest.approx(far / 2)


def test_distance_unknown_for_classes_without_a_typical_size():
    assert estimate_distance_m("frisbee", 100, focal_px=1000) is None
    assert estimate_distance_m("person", 0, focal_px=1000) is None


def test_pick_targets_prefers_longest_seen_then_biggest():
    tracks = [track(1, h=50), track(2, h=300), track(3, h=100), track(4, h=80), track(5, h=60)]
    first_seen = {1: 0.0, 2: 5.0, 3: 1.0, 4: 2.0, 5: 3.0}
    picked = pick_targets(tracks, first_seen, max_n=4)
    assert [t.id for t in picked] == [1, 3, 4, 5]


def test_assign_frequencies_keeps_existing_and_fills_gaps():
    previous = {7: TARGET_FREQS_HZ[0], 9: TARGET_FREQS_HZ[2]}
    result = assign_frequencies([9, 11, 7], previous)
    assert result[7] == TARGET_FREQS_HZ[0]  # an object keeps its frequency while tracked
    assert result[9] == TARGET_FREQS_HZ[2]
    assert result[11] in (TARGET_FREQS_HZ[1], TARGET_FREQS_HZ[3])
    assert previous == {7: TARGET_FREQS_HZ[0], 9: TARGET_FREQS_HZ[2]}  # input untouched
    assert len(set(result.values())) == 3  # no two objects share a frequency


def test_assign_frequencies_drops_lost_objects():
    assert assign_frequencies([], {7: TARGET_FREQS_HZ[0]}) == {}


def test_steering_offset_signs():
    assert steering_offset((0, 0, 100, 10), frame_width=1000) == pytest.approx(-0.9)  # far left
    assert steering_offset((450, 0, 550, 10), frame_width=1000) == pytest.approx(0.0)  # centered
    assert steering_offset((900, 0, 1000, 10), frame_width=1000) == pytest.approx(0.9)  # far right


def test_relevant_class_ids_keeps_only_wheelchair_relevant_names():
    from vision.detect_track import relevant_class_ids

    names = {0: "person", 56: "chair", 63: "laptop", 67: "cell phone", 45: "bowl", 60: "dining table"}
    assert relevant_class_ids(names) == [0, 56, 60]
