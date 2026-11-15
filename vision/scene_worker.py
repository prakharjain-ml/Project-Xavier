"""Object detection and route planning on a background thread, so the screen never waits for them.

Why: detection takes about 60 ms and route planning about 30 ms. Run inside the screen loop, every detection
froze the picture and the gaze cursor for that long, which is what made the screen stutter. On this thread
they run at their own pace, and the screen loop just picks up the newest finished result each pass.

Safety: every result carries the time its camera frame arrived (frame_t). The drive logic stamps its intent with
that time, so if this thread stalls or dies, results stop getting newer and the state machine's stale-data rule
stops the chair, exactly as for a frozen camera. alive() lets the screen end the session when the thread is dead.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field

import numpy as np

from vision.detect_track import Track, pick_targets

log = logging.getLogger("vision.scene_worker")

MAX_CHOOSABLE = 6  # at most this many objects can be chosen at once (the steadiest ones)
IDLE_WAIT_S = 0.005  # nothing new to do: check again this soon (short, so a new frame is picked up quickly)
STOP_JOIN_TIMEOUT_S = 2.0


@dataclass(frozen=True, eq=False)  # eq=False: numpy fields cannot be compared with ==
class Scene:
    """One finished pass: what was seen in one camera frame, and the route to the destination in it."""
    frame: np.ndarray
    frame_t: float  # arrival time of that camera frame (monotonic clock)
    tracks: list[Track]  # every tracked object: the planner's obstacles
    targets: list[Track]  # the few the rider can choose
    destination: int | None = None  # which destination the route below was planned for
    route: object | None = None  # vision.floor_route.Route in image pixels, or None
    route_m: np.ndarray | None = field(default=None)  # the same route in metres in the chair's frame, or None


class SceneWorker:
    """detect(frame) -> tracks.  plan(frame, tracks, target) -> (route, route_m).  Both run on this thread only."""

    def __init__(self, reader, detect: Callable, plan: Callable | None, period_s: float) -> None:
        self._reader, self._detect, self._plan, self._period_s = reader, detect, plan, period_s
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._latest: Scene | None = None
        self._destination: int | None = None
        self._first_seen: dict[int, float] = {}
        self._error: BaseException | None = None
        self._thread = threading.Thread(target=self._run, name="scene-worker", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join(timeout=STOP_JOIN_TIMEOUT_S)

    def set_destination(self, target_id: int | None) -> None:
        """The object the rider confirmed (None = none). The next pass plans a route to it."""
        with self._lock:
            self._destination = target_id

    def latest(self) -> Scene | None:
        with self._lock:
            return self._latest

    def alive(self) -> bool:
        return self._thread.is_alive() and self._error is None

    @property
    def error(self) -> BaseException | None:
        return self._error

    def step(self, frame: np.ndarray, frame_t: float) -> Scene:
        """One pass on one frame (also called directly by tests)."""
        tracks = self._detect(frame)
        now = time.monotonic()
        self._first_seen = {**{t.id: now for t in tracks if t.id not in self._first_seen}, **self._first_seen}
        # Objects may overlap in the picture (a chair in front of the couch you want): both stay choosable. The
        # old "well separated" rule came from the flicker-box design, and it hid the object behind an obstacle.
        targets = pick_targets(tracks, self._first_seen, max_n=MAX_CHOOSABLE)
        with self._lock:
            destination = self._destination
        route = route_m = None
        chosen = next((t for t in targets if t.id == destination), None)
        if self._plan is not None and chosen is not None:
            route, route_m = self._plan(frame, tracks, chosen)
        return Scene(frame, frame_t, tracks, targets, destination if chosen is not None else None, route, route_m)

    def _run(self) -> None:
        last_t, next_pass = None, 0.0
        try:
            while not self._stop.is_set():
                snapshot = self._reader.latest()
                now = time.monotonic()
                if snapshot is None or snapshot[1] == last_t or now < next_pass:
                    self._stop.wait(IDLE_WAIT_S)
                    continue
                frame, last_t = snapshot
                next_pass = now + self._period_s
                scene = self.step(frame, last_t)
                with self._lock:
                    self._latest = scene
        except Exception as error:  # noqa: BLE001 - recorded and shown; the screen ends the session on alive()
            log.exception("detection thread died: no new detections, the chair will stop (stale data)")
            self._error = error
