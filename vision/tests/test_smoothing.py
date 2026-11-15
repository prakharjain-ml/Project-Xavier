"""Screen smoothing (vision/smoothing.py): steady cursor on a fixation, quick on a glance, gliding outlines."""

import numpy as np

from vision.detect_track import Track
from vision.smoothing import RESET_AFTER_S, EuroState, glide_tracks, one_euro

RATE_HZ = 30.0


def run_filter(points):
    state, out = EuroState(), []
    for i, p in enumerate(points):
        state, drawn = one_euro(state, p, i / RATE_HZ)
        out.append(drawn)
    return out


def test_shaky_fixation_is_much_steadier_after_the_filter():
    rng = np.random.default_rng(0)
    raw = [(0.5 + rng.normal(0, 0.02), 0.5 + rng.normal(0, 0.02)) for _ in range(90)]  # 3 s staring at one spot
    smoothed = np.array(run_filter(raw)[30:])
    raw_spread = np.array(raw[30:]).std(axis=0).mean()
    assert smoothed.std(axis=0).mean() < raw_spread / 3  # shake cut to under a third
    assert np.allclose(smoothed.mean(axis=0), (0.5, 0.5), atol=0.01)  # and still centred on the right spot


def test_a_glance_to_another_object_arrives_quickly():
    raw = [(0.2, 0.5)] * 30 + [(0.8, 0.5)] * 30  # jump across the screen
    out = run_filter(raw)
    frames_to_arrive = next(i for i, p in enumerate(out[30:]) if abs(p[0] - 0.8) < 0.05)
    assert frames_to_arrive <= 4  # within about 0.13 s at 30 Hz


def test_no_gaze_draws_nothing_and_a_long_gap_starts_fresh():
    state, drawn = one_euro(EuroState(), (0.2, 0.2), 0.0)
    state, drawn = one_euro(state, None, 0.1)
    assert drawn is None and state.point == (0.2, 0.2)
    _, drawn = one_euro(state, (0.9, 0.9), RESET_AFTER_S + 0.2)
    assert drawn == (0.9, 0.9)  # after a long gap the cursor appears where the eyes are, no slow glide


def test_outlines_glide_toward_the_new_detection_and_vanished_objects_disappear():
    outline = np.array([[100, 100], [200, 100], [200, 300], [100, 300]], float)
    old = Track(1, "chair", 0.9, (100, 100, 200, 300), 2.0, outline)
    moved = Track(1, "chair", 0.9, (140, 100, 240, 300), 2.0, outline + (40, 0))
    gone = Track(2, "couch", 0.9, (500, 100, 700, 300), 3.0)
    drawn = glide_tracks({1: old, 2: gone}, [moved])
    assert set(drawn) == {1}  # the couch is no longer detected: not drawn
    x1 = drawn[1].bbox[0]
    assert 100 < x1 < 140  # part of the way there, not a jump
    assert np.allclose(drawn[1].outline[:, 0].min(), x1)  # the outline moved with the box
    assert np.array_equal(moved.outline, outline + (40, 0))  # the detection itself was not changed


def test_a_new_object_appears_where_it_is():
    new = Track(5, "chair", 0.9, (10, 10, 50, 90), 2.0)
    assert glide_tracks({}, [new])[5].bbox == new.bbox
