"""Where the web session gets its pictures, objects, routes and gaze from.

LivePerception hands the session a forward-camera reader (newest frame only), a vision.scene_worker.SceneWorker
(detection + route planning on its own thread, so nothing waits for YOLO), and the newest GazeSample from the
existing gaze tracker process. Real devices only: there is no simulated room or mouse-as-gaze.
"""

from __future__ import annotations

import logging

from vision.detect_track import Track, focal_length_px
from vision.gaze import GazeSample

log = logging.getLogger("interface.web.perception")

DETECT_PERIOD_S = 0.15  # same as vision.object_select.DETECT_PERIOD_S


# ---------------------------------------------------------------- perception
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
