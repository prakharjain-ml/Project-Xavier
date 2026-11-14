"""Pure gaze math (vision/gaze.py). Synthetic landmarks: no camera, no mediapipe."""

import numpy as np
import pytest

from vision.gaze import (
    ARROW_REGIONS,
    BLINK_MAX_S,
    BlinkState,
    Calibration,
    eye_features,
    eye_openness,
    fit_calibration,
    load_calibration,
    pick_region,
    predict,
    save_calibration,
    smooth,
    update_blink,
)
from vision.gaze import LM  # landmark index names

N_POINTS = 478


def face(iris_shift=(0.0, 0.0), lid_gap=0.02, nose_shift=(0.0, 0.0)):
    """A frontal face in normalized image coords. iris_shift moves both irises; lid_gap opens/closes the eyes."""
    p = np.full((N_POINTS, 2), 0.5)
    for (outer, inner, upper, lower, iris), cx in (
        ((LM.A_OUTER, LM.A_INNER, LM.A_UPPER, LM.A_LOWER, LM.A_IRIS), 0.42),
        ((LM.B_INNER, LM.B_OUTER, LM.B_UPPER, LM.B_LOWER, LM.B_IRIS), 0.58),
    ):
        p[outer] = (cx - 0.04, 0.45)
        p[inner] = (cx + 0.04, 0.45)
        p[upper] = (cx, 0.45 - lid_gap / 2)
        p[lower] = (cx, 0.45 + lid_gap / 2)
        p[iris] = (cx + iris_shift[0], 0.45 + iris_shift[1])
    p[LM.CHEEK_A], p[LM.CHEEK_B] = (0.35, 0.5), (0.65, 0.5)
    p[LM.FOREHEAD], p[LM.CHIN] = (0.5, 0.3), (0.5, 0.7)
    p[LM.NOSE] = (0.5 + nose_shift[0], 0.5 + nose_shift[1])
    return p


def test_features_follow_the_iris_and_head():
    centre = eye_features(face())
    right = eye_features(face(iris_shift=(0.01, 0.0)))
    turned = eye_features(face(nose_shift=(0.03, 0.0)))
    assert centre.shape == (6,)
    assert right[0] > centre[0] and right[2] > centre[2]  # both eyes' horizontal feature increases
    assert turned[4] > centre[4]  # head-turn feature
    assert np.allclose(centre[[0, 2]], 0.5)  # iris midway between the corners


def test_openness_drops_when_eyes_close():
    assert eye_openness(face(lid_gap=0.02)) > 2 * eye_openness(face(lid_gap=0.004))


def test_calibration_recovers_a_known_mapping():
    rng = np.random.default_rng(0)
    samples = []
    for tx, ty in [(x, y) for x in (0.1, 0.5, 0.9) for y in (0.1, 0.5, 0.9)]:
        for _ in range(20):  # gaze target -> iris shift, plus measurement noise
            shift = ((tx - 0.5) * 0.02 + rng.normal(0, 0.0005), (ty - 0.5) * 0.01 + rng.normal(0, 0.0005))
            samples.append((eye_features(face(iris_shift=shift)), (tx, ty)))
    cal = fit_calibration(samples, open_ratio=0.25)
    test = eye_features(face(iris_shift=((0.7 - 0.5) * 0.02, (0.3 - 0.5) * 0.01)))
    x, y = predict(cal, test)
    assert x == pytest.approx(0.7, abs=0.05) and y == pytest.approx(0.3, abs=0.05)


def test_calibration_round_trips_through_json(tmp_path):
    cal = Calibration(mean=(0.0,) * 6, std=(1.0,) * 6, weights=tuple((0.1, 0.2) for _ in range(28)), open_ratio=0.3)
    path = tmp_path / "cal.json"
    save_calibration(cal, path)
    assert load_calibration(path) == cal


def test_fit_needs_enough_points():
    with pytest.raises(ValueError, match="at least"):
        fit_calibration([(np.zeros(6), (0.5, 0.5))] * 3, open_ratio=0.25)


def test_smooth_moves_part_way():
    assert smooth(None, (1.0, 1.0)) == (1.0, 1.0)
    x, y = smooth((0.0, 0.0), (1.0, 1.0), alpha=0.25)
    assert (x, y) == pytest.approx((0.25, 0.25))


def test_pick_region_basic_and_centre_is_none():
    assert pick_region((0.5, 0.1), ARROW_REGIONS, current=None) == "FWD"
    assert pick_region((0.1, 0.5), ARROW_REGIONS, current=None) == "LEFT"
    assert pick_region((0.5, 0.5), ARROW_REGIONS, current=None) is None  # resting in the middle selects nothing


def test_pick_region_hysteresis_holds_near_border_but_not_far():
    regions = {"A": (0.0, 0.0, 0.5, 1.0), "B": (0.5, 0.0, 1.0, 1.0)}
    assert pick_region((0.49, 0.5), regions, current=None, margin=0.03) is None  # too close to the edge to enter
    assert pick_region((0.52, 0.5), regions, current="A", margin=0.03) == "A"  # just over the border: keep A
    assert pick_region((0.60, 0.5), regions, current="A", margin=0.03) == "B"  # clearly in B: switch


def test_blink_shorter_than_limit_keeps_last_gaze():
    state, out = update_blink(BlinkState(), point=(0.5, 0.1), closed=False, now=0.0)
    assert out == (0.5, 0.1)
    state, out = update_blink(state, point=None, closed=True, now=0.1)
    assert out == (0.5, 0.1)  # blink starts: hold
    # Times are literal requirements, NOT derived from BLINK_MAX_S (a test that scales with the constant it
    # checks can never catch a wrong constant): a normal 0.25 s blink must hold; 0.5 s closed must stop.
    state, out = update_blink(state, point=None, closed=True, now=0.1 + 0.25)
    assert out == (0.5, 0.1)  # still inside a normal blink: keep holding
    state, out = update_blink(state, point=None, closed=True, now=0.1 + 0.5)
    assert out is None  # held too long: eyes really closed -> no gaze -> chair stops


def test_no_face_is_no_gaze_immediately():
    state, _ = update_blink(BlinkState(), point=(0.5, 0.1), closed=False, now=0.0)
    _, out = update_blink(state, point=None, closed=False, now=0.05)
    assert out is None


def test_blink_state_is_immutable():
    state = BlinkState()
    update_blink(state, point=(0.1, 0.1), closed=False, now=0.0)
    assert state.last_point is None


def _identity_like_calibration():
    """Calibration fitted on synthetic data so iris shift maps to screen position."""
    samples = []
    for tx, ty in [(x, y) for x in (0.1, 0.5, 0.9) for y in (0.1, 0.5, 0.9)]:
        samples.append((eye_features(face(iris_shift=((tx - 0.5) * 0.02, (ty - 0.5) * 0.01))), (tx, ty)))
    return fit_calibration(samples * 3, open_ratio=0.25)


def test_gaze_step_open_eyes_gives_a_point_closed_eyes_hold_then_none():
    from vision.gaze import GazeState, gaze_step

    cal = _identity_like_calibration()
    state, s1 = gaze_step(face(iris_shift=(0.0, -0.004)), cal, GazeState(), now=0.0)  # looking up
    assert s1.face and not s1.closed and s1.y < 0.3
    state, s2 = gaze_step(face(lid_gap=0.003), cal, state, now=0.1)  # blink begins
    assert s2.closed and s2.point == s1.point
    _, s3 = gaze_step(face(lid_gap=0.003), cal, state, now=0.7)  # still closed 0.6 s later
    assert s3.point is None


def test_gaze_step_no_face():
    from vision.gaze import GazeState, gaze_step

    _, sample = gaze_step(None, _identity_like_calibration(), GazeState(), now=1.0)
    assert not sample.face and sample.point is None and sample.t == 1.0


def test_blink_holds_the_smoothed_point_not_the_raw_one():
    from vision.gaze import GazeState, gaze_step

    cal = _identity_like_calibration()
    state, _ = gaze_step(face(iris_shift=(0.0, -0.004)), cal, GazeState(), now=0.0)  # up
    state, moving = gaze_step(face(iris_shift=(0.008, 0.0)), cal, state, now=0.03)  # jump right: smoothed lags
    _, blink = gaze_step(face(lid_gap=0.003), cal, state, now=0.06)
    assert blink.point == moving.point  # the screen cursor does not jump when the rider blinks
