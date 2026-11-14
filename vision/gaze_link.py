"""Start the eye tracker program and receive its gaze samples. No pygame and no cv2 here, so both the pygame
screen (app.py) and the OpenCV object view (vision/object_select.py) can use it.

The tracker runs as its own program (`python -m vision.gaze_tracker --port N`), not a multiprocessing child:
a spawned child re-imports the launching script, and pygame + cv2 in one process clash (SDL2; it sent 0 samples).
"""

from __future__ import annotations

import os
import queue
import socket
import subprocess
import sys
import threading
import time

from vision.gaze import decode_gaze_message
from vision.gaze_tracker import offer_latest
from vision.gaze_tracker_eyetrax import EYETRAX_PYTHON
from vision.gaze_tracker_eyetrax import MODEL_PATH as EYETRAX_MODEL

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def gaze_backend() -> str:
    """'eyetrax' (default when its environment exists: judged more accurate live) or 'builtin' (ours).
    Override with GAZE_BACKEND=builtin|eyetrax."""
    choice = os.environ.get("GAZE_BACKEND")
    if choice in ("eyetrax", "builtin"):
        return choice
    return "eyetrax" if os.path.exists(EYETRAX_PYTHON) else "builtin"


def calibration_ready(backend: str, calibration: str) -> bool:
    return os.path.exists(os.path.join(REPO_ROOT, EYETRAX_MODEL) if backend == "eyetrax" else calibration)


def calibration_hint(backend: str) -> str:
    if backend == "eyetrax":
        return "~/venvs/eyetrax/bin/python -m vision.gaze_tracker_eyetrax --calibrate-only"
    return "python -m vision.gaze_calibrate"


def calibrate_eyetrax(eye_camera="auto") -> bool:
    """Run EyeTrax's 9-point calibration (its own full-screen window) and wait. True if a model was saved."""
    result = subprocess.run([EYETRAX_PYTHON, "-m", "vision.gaze_tracker_eyetrax", "--calibrate-only",
                             "--eye-camera", str(eye_camera)], cwd=REPO_ROOT)
    return result.returncode == 0


def tracker_command(backend: str, eye_camera, calibration: str, port: int) -> list[str]:
    if backend == "eyetrax":
        return [EYETRAX_PYTHON, "-m", "vision.gaze_tracker_eyetrax", "--eye-camera", str(eye_camera),
                "--port", str(port)]
    return [sys.executable, "-m", "vision.gaze_tracker", "--eye-camera", str(eye_camera),
            "--calibration", calibration, "--port", str(port)]


def start_gaze_tracker(eye_camera, calibration: str, backend: str | None = None):
    """Returns (process, queue of GazeSample (latest only), stop event). Set the event and terminate the
    process when done; the tracker also exits by itself if its parent dies."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", 0))  # any free port; the tracker is told which one
    sock.settimeout(0.2)
    port = sock.getsockname()[1]
    process = subprocess.Popen(tracker_command(backend or gaze_backend(), eye_camera, calibration, port),
                               cwd=REPO_ROOT)
    gaze_queue, stop = queue.Queue(maxsize=1), threading.Event()

    def receive() -> None:
        while not stop.is_set():
            try:
                raw = sock.recv(4096)
            except socket.timeout:
                continue
            except OSError:
                break
            sample = decode_gaze_message(raw, time.monotonic())  # stamped with OUR clock on arrival
            if sample is not None:  # invalid messages are dropped whole (INTERFACES.md transport rule)
                offer_latest(gaze_queue, sample)
        sock.close()

    threading.Thread(target=receive, name="gaze-receiver", daemon=True).start()
    return process, gaze_queue, stop
