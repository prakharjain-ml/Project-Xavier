"""Camera input for vision/: a Ring RTSP stream, a USB webcam, or a video file, through one interface.

Why a background thread that keeps only the newest frame:
network cameras (the Ring via ring-mqtt) deliver frames in bursts and OpenCV queues them. If the display
loop reads them one by one it falls further and further behind real time. The reader thread drains the
stream as fast as it arrives and keeps only the latest frame, so whatever we show (and later steer on)
is as fresh as the camera allows.

This module imports cv2, so it must never be imported by interface/ (SDL2 clash with pygame on macOS).
"""

from __future__ import annotations

import logging
import re
import threading
import time
from collections import deque
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

import cv2
import numpy as np

log = logging.getLogger(__name__)

RECONNECT_S = 2.0  # wait between attempts to (re)open a camera that failed or dropped
STALE_S = 1.0  # no new frame for this long while "connected" means the picture is frozen
FPS_WINDOW_S = 2.0  # FPS is averaged over this many recent seconds
SYNTHETIC_FPS = 30.0
SYNTHETIC_SIZE = (640, 360)

CONNECTING = "CONNECTING"
LIVE = "LIVE"
STALE = "STALE"

_CREDENTIALS = re.compile(r"(?<=://)[^/@]+@")  # the "user:password@" part of a URL


def parse_source(text: str) -> int | str:
    """Turn the --source text into what OpenCV expects: an int for a webcam, a string otherwise."""
    cleaned = text.strip()
    if not cleaned:
        raise ValueError(
            "camera source is empty: pass --source 0 (webcam), an rtsp:// URL, a video file, "
            "or set RING_RTSP_URL"
        )
    return int(cleaned) if cleaned.isdigit() else cleaned


def redact_url(source: int | str) -> str:
    """A label that is safe to print or draw: hides any password inside an RTSP URL."""
    if isinstance(source, int):
        return f"webcam {source}"
    return _CREDENTIALS.sub("***@", source)


def rolling_fps(timestamps: Sequence[float], window_s: float = FPS_WINDOW_S) -> float:
    """Frames per second over the last window_s seconds, from frame arrival times."""
    if len(timestamps) < 2:
        return 0.0
    newest = timestamps[-1]
    recent = [t for t in timestamps if newest - t <= window_s]
    span = recent[-1] - recent[0]
    # n timestamps enclose n - 1 intervals; that is what FPS counts.
    return (len(recent) - 1) / span if span > 0 else 0.0


def make_synthetic_frame(index: int, width: int = SYNTHETIC_SIZE[0], height: int = SYNTHETIC_SIZE[1]) -> np.ndarray:
    """A test picture: a moving orange bar (proves motion) and the frame number."""
    frame = np.zeros((height, width, 3), np.uint8)
    x = (index * 8) % width
    frame[:, x : x + 20] = (0, 160, 255)  # OpenCV colors are BGR, so this is orange
    cv2.putText(frame, f"synthetic frame {index}", (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)
    return frame


class SyntheticCapture:
    """Behaves like cv2.VideoCapture but produces test frames at a steady rate (for --synthetic and tests)."""

    def __init__(self, fps: float = SYNTHETIC_FPS) -> None:
        self._period_s = 1.0 / fps
        self._index = 0
        self._next_t = time.monotonic()

    def isOpened(self) -> bool:  # noqa: N802 - same name as OpenCV's method
        return True

    def read(self) -> tuple[bool, np.ndarray]:
        # Pace like a real camera: wait until this frame is "due".
        delay = self._next_t - time.monotonic()
        if delay > 0:
            time.sleep(delay)
        self._next_t += self._period_s
        self._index += 1
        return True, make_synthetic_frame(self._index)

    def release(self) -> None:
        pass


def open_capture(source: int | str) -> Any:
    """Open a camera with the right OpenCV backend. Returns an object with read()/isOpened()/release()."""
    if isinstance(source, str) and source.startswith("rtsp://"):
        capture = cv2.VideoCapture(source, cv2.CAP_FFMPEG)
    else:
        capture = cv2.VideoCapture(source)
    capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)  # ask for a tiny queue; some backends ignore it, the thread covers that
    return capture


@dataclass(frozen=True)
class CameraStats:
    """A read-only snapshot of how the camera is doing, for the overlay and the logs."""

    status: str
    fps: float
    width: int
    height: int
    frames: int
    frame_age_s: float | None  # seconds since the newest frame reached the laptop; None before the first one


class LatestFrameReader:
    """Reads a camera on a background thread and always holds only the newest frame.

    It never raises into the caller: if the camera is missing or drops, status becomes CONNECTING and it
    retries every reconnect_s seconds.
    """

    def __init__(
        self,
        source: int | str,
        reconnect_s: float = RECONNECT_S,
        opener: Callable[[int | str], Any] = open_capture,
    ) -> None:
        self._source = source
        self._reconnect_s = reconnect_s
        self._opener = opener
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._latest: tuple[np.ndarray, float] | None = None
        self._arrivals: deque[float] = deque(maxlen=300)
        self._frames = 0
        self._connected = False

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="camera-reader", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)

    def latest(self) -> tuple[np.ndarray, float] | None:
        """The newest (frame, arrival time). The frame is never modified afterwards, so it is safe to use."""
        with self._lock:
            return self._latest

    def stats(self) -> CameraStats:
        with self._lock:
            latest, connected = self._latest, self._connected
            arrivals, frames = list(self._arrivals), self._frames
        age = None if latest is None else time.monotonic() - latest[1]
        if not connected:
            status = CONNECTING
        elif age is None or age > STALE_S:
            status = STALE
        else:
            status = LIVE
        height, width = (0, 0) if latest is None else latest[0].shape[:2]
        return CameraStats(status, rolling_fps(arrivals), width, height, frames, age)

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                capture = self._opener(self._source)
            except Exception:  # a broken URL or driver must not kill the thread; we log and retry
                log.exception("camera open failed for %s", redact_url(self._source))
                capture = None
            if capture is not None and capture.isOpened():
                log.info("camera opened: %s", redact_url(self._source))
                self._read_until_failure(capture)
            if capture is not None:
                capture.release()
            self._set_connected(False)
            self._stop.wait(self._reconnect_s)

    def _read_until_failure(self, capture: Any) -> None:
        self._set_connected(True)
        while not self._stop.is_set():
            ok, frame = capture.read()
            if not ok or frame is None:
                log.warning("camera stream ended or dropped: %s", redact_url(self._source))
                return
            arrived = time.monotonic()
            with self._lock:
                # Replace the reference instead of writing into the old array: anyone holding the
                # previous frame keeps an unchanged picture.
                self._latest = (frame, arrived)
                self._arrivals.append(arrived)
                self._frames += 1

    def _set_connected(self, connected: bool) -> None:
        with self._lock:
            self._connected = connected
