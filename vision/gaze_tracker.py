"""Camera + MediaPipe side of gaze tracking. The only file that imports mediapipe.

Runs as its OWN PROCESS (decision D3): cv2 and pygame both bundle SDL2 and must not share a process on macOS.
cv2 and mediapipe are therefore imported inside functions, so `app.py` can import this module (to start the
process) without loading cv2 into the screen process.

The model file is downloaded once to ~/hp26-models/face_landmarker/ (outside the repo, like the YOLO weights):
https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task
"""

from __future__ import annotations

import logging
import os
import time
from queue import Empty, Full

import numpy as np

from vision.gaze import GazeState, gaze_step, load_calibration

log = logging.getLogger("vision.gaze_tracker")

MODEL_PATH = os.path.expanduser(os.environ.get("GAZE_MODEL", "~/hp26-models/face_landmarker/face_landmarker.task"))
CALIBRATION_PATH = "data/raw/gaze_calibration.json"  # gitignored: personal calibration data
DETECT_WIDTH = 640  # pixels; landmark detection runs on a shrunken copy of each frame


class FaceLandmarkSource:
    """Reads the eye camera and returns (frame, landmarks); landmarks is a (478, 2) array or None (no face)."""

    def __init__(self, camera_index: int, model_path: str = MODEL_PATH) -> None:
        import cv2
        import mediapipe as mp

        if not os.path.exists(model_path):
            raise FileNotFoundError(f"face model missing at {model_path} (see module docstring for the URL)")
        self._cv2, self._mp = cv2, mp
        self._cap = cv2.VideoCapture(camera_index)
        if not self._cap.isOpened():
            raise RuntimeError(f"cannot open eye camera {camera_index}")
        vision = mp.tasks.vision
        options = vision.FaceLandmarkerOptions(
            base_options=mp.tasks.BaseOptions(model_asset_path=model_path),
            running_mode=vision.RunningMode.VIDEO, num_faces=1)
        self._landmarker = vision.FaceLandmarker.create_from_options(options)
        self._t0, self._last_ms = time.monotonic(), -1

    def read(self) -> tuple[np.ndarray | None, np.ndarray | None]:
        ok, frame = self._cap.read()
        if not ok or frame is None:
            return None, None
        # VIDEO mode needs strictly increasing timestamps in ms.
        ms = max(int((time.monotonic() - self._t0) * 1000), self._last_ms + 1)
        self._last_ms = ms
        # Shrink before detection: landmarks come back normalized, so a smaller image gives the same points
        # several times faster (full 1920x1080 frames ran at ~3 FPS).
        height, width = frame.shape[:2]
        scale = min(1.0, DETECT_WIDTH / width)
        small = self._cv2.resize(frame, (int(width * scale), int(height * scale))) if scale < 1 else frame
        rgb = self._cv2.cvtColor(small, self._cv2.COLOR_BGR2RGB)
        result = self._landmarker.detect_for_video(self._mp.Image(image_format=self._mp.ImageFormat.SRGB, data=rgb), ms)
        if not result.face_landmarks:
            return frame, None
        # MediaPipe gives x as a fraction of image WIDTH and y as a fraction of HEIGHT. Convert to pixels so both
        # axes use the same unit; otherwise vertical distances are stretched by the aspect ratio (16:9 -> 1.78x).
        return frame, np.array([(p.x * width, p.y * height) for p in result.face_landmarks[0]])

    def close(self) -> None:
        self._landmarker.close()
        self._cap.release()


def offer_latest(q, item) -> None:
    """Latest-only put for a maxsize=1 queue (multiprocessing or queue.Queue). Never blocks."""
    try:
        q.get_nowait()
    except Empty:
        pass
    try:
        q.put_nowait(item)
    except Full:
        pass


def run_gaze_process(out_queue, camera_index: int, calibration_path: str, stop_event,
                     model_path: str = MODEL_PATH) -> None:
    """Child-process entry: camera -> landmarks -> GazeSample -> out_queue, until stop_event is set.

    On any failure it just stops sending; the app then sees stale gaze -> NONE -> the chair stops.
    """
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        cal = load_calibration(calibration_path)
        source = FaceLandmarkSource(camera_index, model_path)
    except Exception:
        log.exception("gaze tracker could not start (no gaze will be sent -> chair stays stopped)")
        return
    state, frames, started = GazeState(), 0, time.monotonic()
    try:
        while not stop_event.is_set():
            frame, points = source.read()
            if frame is None:  # camera hiccup: send nothing; the app treats silence as stale -> STOP
                stop_event.wait(0.01)
                continue
            state, sample = gaze_step(points, cal, state, time.monotonic())
            offer_latest(out_queue, sample)
            frames += 1
    finally:
        source.close()
        elapsed = time.monotonic() - started
        log.info("gaze tracker stopped: %d frames in %.1f s (%.1f FPS)", frames, elapsed, frames / max(elapsed, 1e-6))
