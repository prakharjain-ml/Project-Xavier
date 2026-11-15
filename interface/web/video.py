"""Camera picture -> browser, separate from control. One encoder thread per camera keeps ONLY the newest JPEG;
each viewer gets whatever is newest when it is ready, so a slow browser skips frames instead of building a queue,
and nothing here can slow down the session tick or the motors."""

from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import Callable

import numpy as np

JPEG_QUALITY = 72
MAX_WIDTH = 960          # pictures are shrunk to this width for the stream (the overlay uses frame coordinates)
ENCODE_FPS = 20.0
BOUNDARY = "xavierframe"


class JpegFeed:
    def __init__(self, source: Callable[[], tuple[np.ndarray, float] | None]) -> None:
        self._source = source
        self._lock = threading.Lock()
        self._jpeg: bytes | None = None
        self._frame_t: float | None = None
        self.viewers = 0
        self.encode_ms = 0.0
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="jpeg-feed", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def latest(self) -> tuple[bytes | None, float | None]:
        with self._lock:
            return self._jpeg, self._frame_t

    def _run(self) -> None:
        import cv2

        while not self._stop.is_set():
            self._stop.wait(1 / ENCODE_FPS)
            if self.viewers <= 0:
                continue  # nobody watching: do not spend CPU encoding
            try:
                snap = self._source()
            except Exception:  # the camera went away between sessions: just show nothing new
                snap = None
            if snap is None:  # no session / camera: show nothing rather than the last picture of a past session
                with self._lock:
                    self._jpeg, self._frame_t = None, None
                continue
            if snap[1] == self._frame_t:
                continue  # never encode the same frame twice
            frame, frame_t = snap
            started = time.monotonic()
            if frame.shape[1] > MAX_WIDTH:
                scale = MAX_WIDTH / frame.shape[1]
                frame = cv2.resize(frame, (MAX_WIDTH, int(frame.shape[0] * scale)), interpolation=cv2.INTER_AREA)
            ok, buffer = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
            if ok:
                with self._lock:
                    self._jpeg, self._frame_t = buffer.tobytes(), frame_t
            self.encode_ms = (time.monotonic() - started) * 1000


async def mjpeg(feed: JpegFeed, poll_s: float = 0.02):
    """Async generator for a multipart/x-mixed-replace response (the <img> tag plays it as video)."""
    feed.viewers += 1
    sent_t = None
    try:
        while True:
            jpeg, frame_t = feed.latest()
            if jpeg is not None and frame_t != sent_t:
                sent_t = frame_t
                yield (f"--{BOUNDARY}\r\nContent-Type: image/jpeg\r\nContent-Length: {len(jpeg)}\r\n"
                       f"X-Frame-Time: {frame_t:.3f}\r\n\r\n").encode() + jpeg + b"\r\n"
            await asyncio.sleep(poll_s)
    finally:
        feed.viewers -= 1
