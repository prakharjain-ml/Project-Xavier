"""Live camera viewer with measurable numbers: the first Mode 2 building block.

Shows the camera picture plus an overlay (status, resolution, camera FPS, frame age), logs one line per
second, and prints a one-line summary at exit. Works with the Ring (through the ring-mqtt RTSP bridge),
a USB webcam, a video file, or --synthetic test frames.

Run from the repo root:
    python -m vision.camera_view --synthetic --seconds 10
    python -m vision.camera_view --source 0                      # USB or built-in webcam
    RING_RTSP_URL=rtsp://localhost:8554/<id>_live python -m vision.camera_view
Press q or ESC to quit.

"Frame age" is the time since the newest frame reached the laptop. It shows freezes and stalls; it does
not include the camera's own delay (measure that glass-to-glass with a phone stopwatch, see README).
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from dataclasses import dataclass, replace

import cv2
import numpy as np

from vision.camera_source import (
    LIVE,
    CameraStats,
    LatestFrameReader,
    SyntheticCapture,
    open_capture,
    parse_source,
    redact_url,
)

log = logging.getLogger("vision.camera_view")

WINDOW_NAME = "camera view (q or ESC to quit)"
SOURCE_ENV_VAR = "RING_RTSP_URL"  # keeps the Ring URL (it may hold a password) out of the repo and shell history
DISPLAY_MAX_WIDTH = 1280  # Ring frames can be 1080p or larger; shrink for the window only
DISPLAY_WAIT_MS = 15  # waitKey pause per loop: about 60 window refreshes per second at most
LOG_EVERY_S = 1.0
PLACEHOLDER_SIZE = (360, 640)  # (height, width) of the black screen shown before the first frame
QUIT_KEYS = {ord("q"), 27}  # 27 is ESC
OVERLAY_COLORS = {"LIVE": (0, 220, 0), "STALE": (0, 200, 255), "CONNECTING": (0, 0, 255)}  # BGR


@dataclass(frozen=True)
class ViewSummary:
    """What we report at the end. Updated by building a new copy each time, never edited in place."""

    samples: int = 0
    max_frame_age_s: float = 0.0
    stalls: int = 0  # times the feed went from LIVE to STALE or CONNECTING
    was_live: bool = False


def update_summary(summary: ViewSummary, stats: CameraStats) -> ViewSummary:
    is_live = stats.status == LIVE
    age = stats.frame_age_s if stats.frame_age_s is not None else 0.0
    return replace(
        summary,
        samples=summary.samples + 1,
        max_frame_age_s=max(summary.max_frame_age_s, age) if is_live else summary.max_frame_age_s,
        stalls=summary.stalls + (1 if summary.was_live and not is_live else 0),
        was_live=is_live,
    )


def format_summary(summary: ViewSummary, stats: CameraStats, seconds: float) -> str:
    mean_fps = stats.frames / seconds if seconds > 0 else 0.0
    return (
        f"summary: seconds={seconds:.1f} frames={stats.frames} mean_fps={mean_fps:.1f} "
        f"resolution={stats.width}x{stats.height} max_frame_age_ms={summary.max_frame_age_s * 1000:.0f} "
        f"stalls={summary.stalls} final_status={stats.status}"
    )


def draw_overlay(frame: np.ndarray, stats: CameraStats, label: str) -> np.ndarray:
    """Return a copy of the frame with the numbers drawn on it (the camera frame itself is not touched)."""
    out = frame.copy()
    age_text = "-" if stats.frame_age_s is None else f"{stats.frame_age_s * 1000:.0f} ms"
    lines = [
        f"{stats.status}  {label}",
        f"{stats.width}x{stats.height}  camera {stats.fps:.1f} FPS  frame age {age_text}",
    ]
    color = OVERLAY_COLORS.get(stats.status, (255, 255, 255))
    for row, text in enumerate(lines):
        y = 30 + row * 30
        cv2.putText(out, text, (12, y), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 0), 4)  # dark outline for contrast
        cv2.putText(out, text, (12, y), cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)
    return out


def fit_for_display(frame: np.ndarray) -> np.ndarray:
    height, width = frame.shape[:2]
    if width <= DISPLAY_MAX_WIDTH:
        return frame
    scale = DISPLAY_MAX_WIDTH / width
    return cv2.resize(frame, (DISPLAY_MAX_WIDTH, int(height * scale)), interpolation=cv2.INTER_AREA)


def run_viewer(reader: LatestFrameReader, label: str, seconds: float | None) -> str:
    """Main-thread display loop. Returns the summary line."""
    summary = ViewSummary()
    start = last_log = time.monotonic()
    placeholder = np.zeros((*PLACEHOLDER_SIZE, 3), np.uint8)
    while True:
        now = time.monotonic()
        stats = reader.stats()
        snapshot = reader.latest()
        picture = placeholder if snapshot is None else fit_for_display(snapshot[0])
        cv2.imshow(WINDOW_NAME, draw_overlay(picture, stats, label))
        key = cv2.waitKey(DISPLAY_WAIT_MS) & 0xFF
        if now - last_log >= LOG_EVERY_S:
            summary = update_summary(summary, stats)  # sample once per second, same moments as the log
            age = "-" if stats.frame_age_s is None else f"{stats.frame_age_s * 1000:.0f}ms"
            log.info("status=%s fps=%.1f age=%s frames=%d", stats.status, stats.fps, age, stats.frames)
            last_log = now
        if key in QUIT_KEYS or (seconds is not None and now - start >= seconds):
            return format_summary(summary, reader.stats(), now - start)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Show a live camera feed with FPS and frame-age numbers.")
    parser.add_argument("--source", default=os.environ.get(SOURCE_ENV_VAR, ""),
                        help=f"webcam index (0), rtsp:// URL, or video file; default: ${SOURCE_ENV_VAR}")
    parser.add_argument("--synthetic", action="store_true", help="use generated test frames, no camera needed")
    parser.add_argument("--seconds", type=float, default=None, help="quit automatically after this many seconds")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    args = parse_args(sys.argv[1:] if argv is None else argv)
    if args.synthetic:
        source, opener = "synthetic", (lambda _src: SyntheticCapture())
    else:
        try:
            source, opener = parse_source(args.source), open_capture
        except ValueError as error:
            log.error("%s", error)
            return 2
    reader = LatestFrameReader(source, opener=opener)
    reader.start()
    try:
        line = run_viewer(reader, redact_url(source), args.seconds)
    finally:
        reader.stop()
        cv2.destroyAllWindows()
    print(line)  # the evidence line: paste it into PROGRESS.md
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
