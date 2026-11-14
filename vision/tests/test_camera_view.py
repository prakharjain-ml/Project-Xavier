"""Tests for the pure parts of vision/camera_view.py (no window is opened)."""

import numpy as np

from vision.camera_source import CameraStats
from vision.camera_view import ViewSummary, draw_overlay, format_summary, update_summary


def live_stats(age_s=0.05, status="LIVE"):
    return CameraStats(status=status, fps=15.0, width=640, height=360, frames=100, frame_age_s=age_s)


def test_draw_overlay_returns_new_frame_and_leaves_input_untouched():
    frame = np.zeros((360, 640, 3), np.uint8)
    out = draw_overlay(frame, live_stats(), "webcam 0")
    assert out is not frame
    assert out.shape == frame.shape
    assert not frame.any()  # original still all black
    assert out.any()  # overlay text was drawn on the copy


def test_update_summary_tracks_worst_frame_age_without_mutating():
    start = ViewSummary()
    after = update_summary(start, live_stats(age_s=0.4))
    assert start.max_frame_age_s == 0.0  # original unchanged
    assert after.max_frame_age_s == 0.4
    assert after.samples == 1


def test_update_summary_counts_a_stall_once_per_drop():
    s = update_summary(ViewSummary(), live_stats())
    s = update_summary(s, live_stats(status="STALE", age_s=1.5))
    s = update_summary(s, live_stats(status="STALE", age_s=2.0))  # same stall, not counted again
    s = update_summary(s, live_stats())
    s = update_summary(s, live_stats(status="CONNECTING", age_s=None))
    assert s.stalls == 2


def test_format_summary_is_one_line_with_key_numbers():
    s = update_summary(ViewSummary(), live_stats(age_s=0.25))
    line = format_summary(s, live_stats(), seconds=10.0)
    assert line.startswith("summary: ")
    assert "\n" not in line
    for key in ("seconds=10.0", "frames=100", "mean_fps=", "max_frame_age_ms=250", "stalls=0", "final_status=LIVE"):
        assert key in line
