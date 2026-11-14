"""Pure helpers of the calibration screen (no camera, no window)."""

import numpy as np
import pytest

from vision.gaze_calibrate import calibration_targets, drop_blinks, format_summary, region_accuracy


def test_nine_distinct_targets_inside_the_screen():
    targets = calibration_targets()
    assert len(set(targets)) == 9
    assert all(0.0 < x < 1.0 and 0.0 < y < 1.0 for x, y in targets)


def test_drop_blinks_removes_samples_with_closed_eyes():
    open_sample = (np.zeros(6), (0.1, 0.1), 0.35)
    blink = (np.zeros(6), (0.1, 0.1), 0.05)
    kept, open_ratio = drop_blinks([open_sample] * 10 + [blink] * 2)
    assert len(kept) == 10 and open_ratio == pytest.approx(0.35)


def test_region_accuracy_per_region_and_overall():
    picks = {"FWD": ["FWD"] * 9 + [None], "LEFT": ["LEFT"] * 5 + ["FWD"] * 5}
    per, overall = region_accuracy(picks)
    assert per == {"FWD": 0.9, "LEFT": 0.5}
    assert overall == pytest.approx(14 / 20)


def test_region_accuracy_with_no_samples_is_zero_not_a_crash():
    per, overall = region_accuracy({"FWD": []})
    assert per == {"FWD": 0.0} and overall == 0.0


def test_summary_is_one_line():
    line = format_summary(samples=180, per={"FWD": 0.9, "LEFT": 1.0}, overall=0.95)
    assert line.startswith("summary: ") and "\n" not in line and "accuracy=95%" in line
