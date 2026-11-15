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
import numpy as np

from shared.latest import offer_latest  # noqa: F401  (re-exported for vision/gaze_link.py)
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


def run_gaze_process(emit, camera_index: int, calibration_path: str, should_stop,
                     model_path: str = MODEL_PATH) -> None:
    """camera -> landmarks -> GazeSample -> emit(sample), until should_stop() is true.

    On any failure it just stops emitting; the app then sees stale gaze -> NONE -> the chair stops.
    """
    try:
        cal = load_calibration(calibration_path)
        source = FaceLandmarkSource(camera_index, model_path)
    except Exception:
        log.exception("gaze tracker could not start (no gaze will be sent -> chair stays stopped)")
        return
    state, frames, started = GazeState(), 0, time.monotonic()
    try:
        while not should_stop():
            frame, points = source.read()
            if frame is None:  # camera hiccup: send nothing; the app treats silence as stale -> STOP
                time.sleep(0.01)
                continue
            state, sample = gaze_step(points, cal, state, time.monotonic())
            emit(sample)
            frames += 1
    finally:
        source.close()
        elapsed = time.monotonic() - started
        log.info("gaze tracker stopped: %d frames in %.1f s (%.1f FPS)", frames, elapsed, frames / max(elapsed, 1e-6))


def main(argv: list[str] | None = None) -> int:
    """Run as its own program (launched by app.py --gaze): sends each GazeSample as JSON to 127.0.0.1:<port>.

    A separate program, not a multiprocessing child: a spawned child re-imports app.py (pygame) and then cv2,
    which brings back the SDL2 clash (seen: 0 samples). Exits by itself if the app that started it dies.
    """
    import argparse
    import socket
    import sys

    from vision.gaze import encode_gaze_message

    parser = argparse.ArgumentParser(description="Eye tracker: sends gaze samples over localhost UDP.")
    parser.add_argument("--eye-camera", default="auto", help="camera index, or auto = the camera that sees a face")
    parser.add_argument("--calibration", default=CALIBRATION_PATH)
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if args.eye_camera == "auto":
        from vision.camera_roles import probe_cameras

        faces = [p.index for p in sorted(probe_cameras(), key=lambda p: -p.face_width) if p.sees_face]  # biggest face first
        if not faces:
            log.error("no camera sees a face: sit in front of the laptop camera")
            return 2
        eye_camera = faces[0]
        log.info("eye camera (auto) = %d", eye_camera)
    else:
        eye_camera = int(args.eye_camera)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    parent = os.getppid()

    def emit(sample) -> None:
        try:
            sock.sendto(encode_gaze_message(sample), ("127.0.0.1", args.port))
        except OSError:
            pass  # nobody listening right now: drop it (the app treats gaps as stale -> STOP)

    run_gaze_process(emit, eye_camera, args.calibration, should_stop=lambda: os.getppid() != parent)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
