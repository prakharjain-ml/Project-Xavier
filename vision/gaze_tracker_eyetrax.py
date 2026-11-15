"""EyeTrax gaze source (https://github.com/ck-zhang/eyetrax): the rider judged it more accurate than our own
tracker. It runs in its own environment (~/venvs/eyetrax: EyeTrax needs OpenCV 4.11 + NumPy 1.26, which would
break YOLO in the main environment) and sends the SAME UDP GazeSample messages as vision/gaze_tracker.py, so
app.py and vision/object_select.py work unchanged.

    ~/venvs/eyetrax/bin/python -m vision.gaze_tracker_eyetrax --calibrate-only      # 9-point calibration, saves model
    (app.py / object_select start it themselves with --port N)
"""

from __future__ import annotations

import argparse
import logging
import os
import socket
import sys
import time

from vision.gaze import BlinkState, GazeSample, encode_gaze_message, update_blink

log = logging.getLogger("vision.gaze_tracker_eyetrax")

EYETRAX_PYTHON = os.path.expanduser("~/venvs/eyetrax/bin/python")
MODEL_PATH = "data/raw/eyetrax_model.pkl"  # gitignored: a personal calibration
EMA_ALPHA = 0.25  # EyeTrax's Kalman + EMA smoothing strength (its demo default)


def to_sample(xy_px: tuple[float, float] | None, screen: tuple[int, int], face: bool, blink: bool,
              state: BlinkState, now: float) -> tuple[BlinkState, GazeSample]:
    """EyeTrax output (screen pixels) -> our GazeSample (0-1 screen fractions), with our blink-hold rule."""
    if not face:
        return BlinkState(), GazeSample(None, False, False, now)
    point = None
    if xy_px is not None and not blink:
        point = (min(1.0, max(0.0, xy_px[0] / screen[0])), min(1.0, max(0.0, xy_px[1] / screen[1])))
    state, held = update_blink(state, point, blink, now)
    return state, GazeSample(held, blink, True, now)


def resolve_camera(text: str) -> int:
    if text != "auto":
        return int(text)
    from vision.camera_roles import probe_cameras

    faces = [p.index for p in sorted(probe_cameras(), key=lambda p: -p.face_width) if p.sees_face]  # biggest face first
    if not faces:
        raise RuntimeError("no camera sees a face: sit in front of the laptop camera")
    return faces[0]


def calibrate(camera: int, model_path: str) -> None:
    from eyetrax import GazeEstimator

    from vision.eyetrax_calibration_ui import run_9_point_calibration  # EyeTrax's procedure, Xavier's look

    estimator = GazeEstimator()
    run_9_point_calibration(estimator, camera_index=camera)
    os.makedirs(os.path.dirname(model_path) or ".", exist_ok=True)
    estimator.save_model(model_path)
    log.info("EyeTrax model saved to %s", model_path)


def stream(camera: int, model_path: str, port: int) -> None:
    """Send one GazeSample per camera frame to 127.0.0.1:port until the parent process dies."""
    import cv2
    from eyetrax import GazeEstimator
    from eyetrax.filters import KalmanEMASmoother, make_kalman
    from eyetrax.utils.screen import get_screen_size

    estimator = GazeEstimator()
    estimator.load_model(model_path)
    screen = get_screen_size()
    smoother = KalmanEMASmoother(make_kalman(), ema_alpha=EMA_ALPHA)
    cap = cv2.VideoCapture(camera)
    if not cap.isOpened():
        raise RuntimeError(f"cannot open eye camera {camera}")
    sock, parent, state = socket.socket(socket.AF_INET, socket.SOCK_DGRAM), os.getppid(), BlinkState()
    frames, started = 0, time.monotonic()
    try:
        while os.getppid() == parent:  # exits by itself if app.py / object_select dies
            ok, frame = cap.read()
            if not ok:
                time.sleep(0.01)
                continue
            features, blink = estimator.extract_features(frame)
            xy = None
            if features is not None and not blink:
                x, y = estimator.predict([features])[0]
                xy = smoother.step(int(x), int(y))
            state, sample = to_sample(xy, screen, face=features is not None, blink=bool(blink), state=state,
                                      now=time.monotonic())
            try:
                sock.sendto(encode_gaze_message(sample), ("127.0.0.1", port))
            except OSError:
                pass  # nobody listening right now; the app treats gaps as stale -> STOP
            frames += 1
    finally:
        cap.release()
        log.info("EyeTrax tracker stopped: %d frames in %.1f s", frames, time.monotonic() - started)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="EyeTrax gaze tracker -> localhost UDP")
    parser.add_argument("--eye-camera", default="auto")
    parser.add_argument("--model", default=MODEL_PATH)
    parser.add_argument("--port", type=int)
    parser.add_argument("--calibrate-only", action="store_true", help="run the 9-point calibration and exit")
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    try:
        camera = resolve_camera(args.eye_camera)
        if args.calibrate_only:
            calibrate(camera, args.model)
            return 0
        if args.port is None:
            parser.error("--port is required unless --calibrate-only")
        stream(camera, args.model, args.port)
    except Exception:
        log.exception("EyeTrax tracker failed (no gaze will be sent -> chair stays stopped)")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
