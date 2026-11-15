"""Where the web session gets its pictures, objects, routes and gaze from.

Both implementations hand the session the SAME things: a forward-camera reader (newest frame only), a
vision.scene_worker.SceneWorker (detection + route planning on its own thread, so nothing waits for YOLO), and
the newest GazeSample.

- MockPerception (practice): a still room picture, a few simulated objects that come closer as the mock chair
  drives (from the wheel commands), the REAL planner (object_select.plan_for_drive) and the REAL SceneWorker.
  Gaze = the browser's mouse pointer. No camera, headset or motor is touched.
- LivePerception: the real forward camera (LatestFrameReader), YOLO detection, and the existing gaze tracker
  process (vision.gaze_link.start_gaze_tracker). Opened only when a human starts a live session.
"""

from __future__ import annotations

import logging
import math
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from control.navigation import MAX_SPEED, NavConfig
from vision.detect_track import Track, focal_length_px
from vision.gaze import GazeSample

log = logging.getLogger("interface.web.perception")

ROOM_PICTURE = Path("data/raw/screenshots/room_frame.jpg")  # local only (gitignored); a drawn room if missing
MOCK_FRAME_SIZE = (1280, 720)
MOCK_FPS = 15.0
MOCK_HFOV = 70.0
DETECT_PERIOD_S = 0.15  # same as vision.object_select.DETECT_PERIOD_S
OBJECT_HEIGHT_PX_AT_1M = 420.0  # simulated objects: box height in pixels at 1 m (shrinks as 1/distance)


# ---------------------------------------------------------------- mock world
@dataclass
class MockObject:
    id: int
    label: str
    forward_m: float  # metres ahead of the chair
    left_m: float     # metres to the left
    aspect: float     # box width / height


@dataclass
class MockWorld:
    """A few objects on the floor around the chair. Wheel commands move the chair (so the objects move)."""
    objects: list[MockObject] = field(default_factory=lambda: [
        MockObject(1, "chair", 2.2, 0.55, 0.8), MockObject(2, "couch", 3.6, -1.2, 1.9),
        MockObject(3, "potted plant", 3.0, 1.6, 0.6), MockObject(4, "dining table", 4.4, 0.1, 1.6)])
    lock: threading.Lock = field(default_factory=threading.Lock)

    def drive(self, left: int, right: int, dt: float) -> None:
        """Inverse of control.navigation.to_wheels: firmware wheel speeds -> chair motion for dt seconds."""
        cfg = NavConfig()
        half = cfg.track_width / 2
        top = cfg.max_speed + cfg.max_yaw_rate * half
        v = (left + right) / 2 / MAX_SPEED * top
        w = (right - left) / (2 * half) / MAX_SPEED * top
        dth, dx = w * dt, v * dt
        with self.lock:
            for o in self.objects:  # move the world the opposite way: translate, then rotate by -dth
                x, y = o.forward_m - dx, o.left_m
                o.forward_m = x * math.cos(dth) + y * math.sin(dth)
                o.left_m = -x * math.sin(dth) + y * math.cos(dth)

    def tracks(self, frame_w: int, frame_h: int, hfov: float) -> list[Track]:
        focal = focal_length_px(frame_w, hfov)
        out = []
        with self.lock:
            for o in self.objects:
                if o.forward_m <= 0.25:
                    continue  # behind or under the camera: not visible
                cx = frame_w / 2 - o.left_m / o.forward_m * focal
                h = OBJECT_HEIGHT_PX_AT_1M / o.forward_m
                w = h * o.aspect
                foot = min(frame_h - 1.0, frame_h * 0.62 + 140 / o.forward_m)  # nearer objects sit lower
                box = (cx - w / 2, foot - h, cx + w / 2, foot)
                if box[2] < 0 or box[0] > frame_w:
                    continue
                clipped = (max(0.0, box[0]), max(0.0, box[1]), min(float(frame_w), box[2]), min(float(frame_h), box[3]))
                out.append(Track(o.id, o.label, 0.9, clipped, round(math.hypot(o.forward_m, o.left_m), 2)))
        return out


def _room_picture() -> np.ndarray:
    import cv2

    if ROOM_PICTURE.exists():
        picture = cv2.imread(str(ROOM_PICTURE))
        if picture is not None:
            return cv2.resize(picture, MOCK_FRAME_SIZE)
    w, h = MOCK_FRAME_SIZE  # a plain drawn room: wall, floor, horizon
    picture = np.zeros((h, w, 3), np.uint8)
    picture[: int(h * 0.55)] = (58, 52, 46)
    picture[int(h * 0.55):] = (84, 92, 98)
    return picture


class MockFrameReader:
    """Same interface as vision.camera_source.LatestFrameReader: latest() -> (frame, arrival time)."""

    def __init__(self) -> None:
        self._picture = _room_picture()
        self._stop = threading.Event()
        self._latest: tuple[np.ndarray, float] | None = None
        self._thread = threading.Thread(target=self._run, name="mock-camera", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def latest(self) -> tuple[np.ndarray, float] | None:
        return self._latest

    def _run(self) -> None:
        while not self._stop.is_set():
            self._latest = (self._picture, time.monotonic())  # same picture, new arrival time: a live camera
            self._stop.wait(1 / MOCK_FPS)


# ---------------------------------------------------------------- perception front-ends
class MockPerception:
    kind = "mock"
    hfov = MOCK_HFOV

    def __init__(self) -> None:
        from vision.object_select import plan_for_drive
        from vision.scene_worker import SceneWorker

        self.world = MockWorld()
        self.reader = MockFrameReader()
        detect = lambda frame: self.world.tracks(frame.shape[1], frame.shape[0], self.hfov)  # noqa: E731
        plan = lambda frame, tracks, target: plan_for_drive(frame, tracks, target, self.hfov, 0.9, 0.0)  # noqa: E731
        self.worker = SceneWorker(self.reader, detect, plan, DETECT_PERIOD_S)
        self._pointer: GazeSample | None = None
        self.started = False

    def start(self) -> None:
        self.reader.start()
        self.worker.start()
        self.started = True

    def stop(self) -> None:
        self.worker.stop()
        self.reader.stop()

    def set_pointer(self, point: tuple[float, float] | None, now: float) -> None:
        """Practice mode: the mouse pointer (viewport fraction) is the gaze."""
        self._pointer = GazeSample(point, False, point is not None, now)

    def gaze(self) -> GazeSample | None:
        return self._pointer

    def wheels(self, left: int, right: int, dt: float) -> None:
        self.world.drive(left, right, dt)

    def problem(self) -> str | None:
        return None if self.worker.alive() else f"Object detection stopped ({self.worker.error})."

    def devices(self) -> dict[str, dict]:
        return {"forward_camera": {"status": "streaming", "detail": "Simulated room"},
                "eye_camera": {"status": "not_used", "detail": "Practice uses your mouse as gaze"},
                "headset": {"status": "not_used", "detail": "Practice mode"},
                "chair": {"status": "mock", "detail": "Fake serial port: nothing moves"}}


class LivePerception:
    """Real cameras, YOLO and the gaze tracker. Built only when a human starts a live session."""
    kind = "live"

    def __init__(self, forward_source: int | str, eye_camera: int, calibration: str, hfov: float,
                 device: str = "mps") -> None:
        self.forward_source, self.eye_camera, self.calibration = forward_source, eye_camera, calibration
        self.hfov, self.device = hfov, device
        self.reader = None
        self.worker = None
        self._gaze_queue = self._gaze_stop = self._process = None
        self._sample: GazeSample | None = None
        self.started = False

    def start(self) -> None:
        from ultralytics import YOLO

        from vision.camera_source import LatestFrameReader, open_capture
        from vision.detect_track import DEFAULT_MODEL, SEG_MODEL, detect, relevant_class_ids
        from vision.gaze_link import start_gaze_tracker
        from vision.object_select import plan_for_drive
        from vision.scene_worker import SceneWorker

        self.reader = LatestFrameReader(self.forward_source, opener=open_capture)
        self.reader.start()
        try:
            model = YOLO(SEG_MODEL)
        except Exception as error:  # offline and not downloaded: plain boxes instead of outlines
            log.warning("segmentation model unavailable (%s): boxes instead of outlines", str(error)[:80])
            model = YOLO(DEFAULT_MODEL)
        classes = relevant_class_ids(model.names)
        detect_frame = lambda f: detect(model, f, focal_length_px(f.shape[1], self.hfov), self.device, classes)  # noqa: E731
        plan_frame = lambda f, tracks, target: plan_for_drive(f, tracks, target, self.hfov, 0.9, 0.0)  # noqa: E731
        self.worker = SceneWorker(self.reader, detect_frame, plan_frame, DETECT_PERIOD_S)
        self.worker.start()
        self._process, self._gaze_queue, self._gaze_stop = start_gaze_tracker(self.eye_camera, self.calibration)
        self.started = True

    def stop(self) -> None:
        if self.worker is not None:
            self.worker.stop()
        if self._gaze_stop is not None:
            self._gaze_stop.set()
        if self._process is not None:
            self._process.terminate()
            try:
                self._process.wait(timeout=3)
            except Exception:  # still running after 3 s: make sure no orphan keeps the eye camera
                self._process.kill()
        if self.reader is not None:
            self.reader.stop()

    def set_pointer(self, point, now) -> None:  # the mouse is never gaze in a live session
        return None

    def gaze(self) -> GazeSample | None:
        from shared.latest import drain_newest

        if self._gaze_queue is not None:
            self._sample = drain_newest(self._gaze_queue, self._sample)
        return self._sample

    def wheels(self, left: int, right: int, dt: float) -> None:
        return None  # the real world moves by itself

    def problem(self) -> str | None:
        if self._process is not None and self._process.poll() is not None:
            return "The eye tracker stopped. Check the eye camera, then restart the session."
        if self.worker is not None and not self.worker.alive():
            return f"Object detection stopped ({self.worker.error}). Restart the session."
        return None

    def devices(self) -> dict[str, dict]:
        stats = self.reader.stats() if self.reader is not None else None
        forward = {"status": "opening", "detail": ""}
        if stats is not None:
            forward = {"status": "streaming" if stats.fps > 0 else "no_frames", "detail": f"{stats.fps:.0f} fps"}
        alive = self._process is not None and self._process.poll() is None
        return {"forward_camera": forward,
                "eye_camera": {"status": "streaming" if alive else "error", "detail": "gaze tracker process"},
                "headset": {"status": "unknown", "detail": ""}, "chair": {"status": "unknown", "detail": ""}}
