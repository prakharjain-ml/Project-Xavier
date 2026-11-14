"""Tests for vision/camera_source.py. No network and no real camera: we use generated frames and a temp video."""

import time

import cv2
import numpy as np
import pytest

from vision.camera_source import (
    CONNECTING,
    LatestFrameReader,
    SyntheticCapture,
    make_synthetic_frame,
    parse_source,
    redact_url,
    rolling_fps,
)


def wait_for(condition, timeout_s=3.0):
    """Poll until condition() is true or the timeout passes; returns the final value."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.02)
    return condition()


def test_parse_source_turns_digits_into_webcam_index():
    assert parse_source("0") == 0
    assert parse_source(" 1 ") == 1


def test_parse_source_keeps_urls_and_paths_as_text():
    assert parse_source("rtsp://localhost:8554/abc_live") == "rtsp://localhost:8554/abc_live"
    assert parse_source("clip.mp4") == "clip.mp4"


def test_parse_source_rejects_empty_text():
    with pytest.raises(ValueError, match="camera source is empty"):
        parse_source("   ")


def test_redact_url_hides_password():
    assert redact_url("rtsp://user:secret@localhost:8554/x_live") == "rtsp://***@localhost:8554/x_live"
    assert redact_url("rtsp://localhost:8554/x_live") == "rtsp://localhost:8554/x_live"
    assert redact_url(0) == "webcam 0"


def test_rolling_fps_counts_frames_in_window():
    timestamps = [i * 0.1 for i in range(11)]  # 10 intervals over 1.0 s = 10 FPS
    assert rolling_fps(timestamps) == pytest.approx(10.0)


def test_rolling_fps_ignores_old_frames_and_handles_short_input():
    assert rolling_fps([]) == 0.0
    assert rolling_fps([5.0]) == 0.0
    # Two frames 10 s ago, then 0.5 s of 20 FPS: only the recent burst counts.
    timestamps = [0.0, 0.1] + [10.0 + i * 0.05 for i in range(11)]
    assert rolling_fps(timestamps, window_s=2.0) == pytest.approx(20.0)


def test_synthetic_frame_shape_and_type():
    frame = make_synthetic_frame(3, width=320, height=180)
    assert frame.shape == (180, 320, 3)
    assert frame.dtype == np.uint8


def test_reader_reads_frames_from_a_video_file(tmp_path):
    path = str(tmp_path / "clip.avi")
    writer = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"MJPG"), 30, (160, 120))
    for i in range(30):
        writer.write(make_synthetic_frame(i, width=160, height=120))
    writer.release()

    reader = LatestFrameReader(path, reconnect_s=0.2)
    reader.start()
    try:
        assert wait_for(lambda: reader.stats().frames > 0)
        snapshot = reader.latest()
        assert snapshot is not None
        frame, received_t = snapshot
        assert frame.shape == (120, 160, 3)
        assert received_t <= time.monotonic()
        assert (reader.stats().width, reader.stats().height) == (160, 120)
    finally:
        reader.stop()


def test_reader_survives_a_missing_source(tmp_path):
    reader = LatestFrameReader(str(tmp_path / "missing.avi"), reconnect_s=0.1)
    reader.start()
    try:
        time.sleep(0.3)
        assert reader.latest() is None
        assert reader.stats().status == CONNECTING
    finally:
        reader.stop()


def test_reader_with_synthetic_capture_goes_live():
    reader = LatestFrameReader("synthetic", opener=lambda _source: SyntheticCapture(fps=60))
    reader.start()
    try:
        assert wait_for(lambda: reader.stats().status == "LIVE" and reader.stats().fps > 0)
    finally:
        reader.stop()


def test_latest_returns_a_snapshot_not_the_live_buffer():
    reader = LatestFrameReader("synthetic", opener=lambda _source: SyntheticCapture(fps=60))
    reader.start()
    try:
        assert wait_for(lambda: reader.latest() is not None)
        first, _ = reader.latest()
        before = first.copy()
        time.sleep(0.1)  # the reader keeps replacing frames meanwhile
        assert np.array_equal(first, before)  # our copy was never changed underneath us
    finally:
        reader.stop()
