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


def test_boxes_conflict_when_overlapping_or_too_close():
    from vision.detect_track import boxes_conflict

    assert boxes_conflict((0, 0, 100, 100), (50, 50, 150, 150), min_gap_px=10)  # overlap
    assert boxes_conflict((0, 0, 100, 100), (105, 0, 200, 100), min_gap_px=10)  # 5 px apart: too close
    assert not boxes_conflict((0, 0, 100, 100), (120, 0, 200, 100), min_gap_px=10)  # 20 px apart
    assert not boxes_conflict((0, 0, 100, 100), (0, 130, 100, 200), min_gap_px=10)  # apart vertically


def test_separate_targets_skips_conflicts_and_fills_with_next_best():
    from vision.detect_track import separate_targets

    ranked = [track(1, x1=0), track(2, x1=40), track(3, x1=300), track(4, x1=600), track(5, x1=900)]
    kept = separate_targets(ranked, frame_width=1000, max_n=4)  # min gap 50 px; #2 overlaps #1
    assert [t.id for t in kept] == [1, 3, 4, 5]


def test_new_box_gets_frequency_furthest_from_its_nearest_neighbor():
    previous = {1: TARGET_FREQS_HZ[0]}  # 6.67 Hz already on the left box
    centers = {1: (100, 100), 2: (300, 100)}  # box 2 is right next to box 1
    result = assign_frequencies([1, 2], previous, centers)
    assert result[1] == TARGET_FREQS_HZ[0]
    assert result[2] == TARGET_FREQS_HZ[3]  # 15 Hz: as different from 6.67 Hz as possible


def test_load_hfov_reads_saved_calibration_or_falls_back(tmp_path):
    import json

    from vision.detect_track import DEFAULT_HFOV_DEG, load_hfov

    assert load_hfov(tmp_path / "missing.json") == DEFAULT_HFOV_DEG
    path = tmp_path / "cal.json"
    path.write_text(json.dumps({"hfov_deg": 85.5}))
    assert load_hfov(path) == 85.5
    path.write_text("not json")
    assert load_hfov(path) == DEFAULT_HFOV_DEG  # a broken file never crashes the app


def _fake_result(masks):
    import types

    import torch

    boxes = types.SimpleNamespace(id=torch.tensor([3.0, 5.0]), cls=torch.tensor([0.0, 0.0]),
                                  conf=torch.tensor([0.9, 0.8]),
                                  xyxy=torch.tensor([[10.0, 10.0, 110.0, 210.0], [300.0, 50.0, 400.0, 250.0]]))
    return types.SimpleNamespace(boxes=boxes, masks=masks, names={0: "chair"})


def _fake_model(result):
    import types

    return types.SimpleNamespace(track=lambda *args, **kwargs: [result])


def test_detect_attaches_an_outline_per_object_when_the_model_returns_masks():
    import types

    import numpy as np

    from vision.detect_track import detect

    square = np.array([[10, 10], [110, 10], [110, 210], [10, 210]], np.float32)
    masks = types.SimpleNamespace(xy=[square, np.zeros((0, 2), np.float32)])  # second mask came back empty

    tracks = detect(_fake_model(_fake_result(masks)), np.zeros((480, 640, 3), np.uint8), 500.0, "cpu", None)

    assert [t.id for t in tracks] == [3, 5]
    assert np.array_equal(tracks[0].outline, square)
    assert tracks[1].outline is None  # an empty mask is dropped, the box is still there


def test_detect_without_masks_leaves_outline_empty_and_tracks_still_compare():
    import numpy as np

    from vision.detect_track import Track, detect

    tracks = detect(_fake_model(_fake_result(None)), np.zeros((480, 640, 3), np.uint8), 500.0, "cpu", None)

    assert all(t.outline is None for t in tracks)
    with_outline = Track(1, "chair", 0.9, (0, 0, 1, 1), 2.0, np.zeros((4, 2)))
    assert with_outline == Track(1, "chair", 0.9, (0, 0, 1, 1), 2.0)  # the outline does not take part in ==
