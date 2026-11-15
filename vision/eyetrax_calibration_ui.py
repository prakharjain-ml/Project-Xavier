"""EyeTrax's 9-point calibration with the Xavier look. Runs inside the EyeTrax environment (~/venvs/eyetrax).

Same procedure as eyetrax.calibration.nine_point.run_9_point_calibration, step for step:
1. wait until a face is seen (eyes open), then a 2 s countdown;
2. the same 9 points in the same order (eyetrax compute_grid_points, 10% margin);
3. per point: 1.0 s "pulse" while the eyes travel there, then 1.0 s capture, keeping every frame with a face and
   no blink;
4. gaze_estimator.train(features, targets).
Only the drawing changed (interface.screens) and the window really fills the screen (interface.window).
"""

from __future__ import annotations

import math
import time

import numpy as np

from interface import screens, window

WINDOW = "Calibration"
COUNTDOWN_S = 2.0          # eyetrax: wait_for_face_and_countdown(..., dur=2)
PULSE_S, CAPTURE_S = 1.0, 1.0  # eyetrax: _pulse_and_capture(pulse_d=1.0, cd_d=1.0)
ESC = 27
NINE_POINT_ORDER = [(1, 1), (0, 0), (2, 0), (0, 2), (2, 2), (1, 0), (0, 1), (2, 1), (1, 2)]  # eyetrax's order


def _wait_for_face(cv2, cap, estimator, sw: int, sh: int) -> bool:
    started = None
    while True:
        ok, frame = cap.read()
        if not ok:
            continue
        features, blink = estimator.extract_features(frame)
        face = features is not None and not blink
        now = time.time()
        if face:
            started = now if started is None else started
            if now - started >= COUNTDOWN_S:
                return True
            countdown = (now - started) / COUNTDOWN_S
        else:
            started, countdown = None, None
        window.show(cv2, WINDOW, screens.face_check(sw, sh, face, countdown, "Eye calibration",
                                                    "Keep your head still. Follow the dot with your eyes."))
        if cv2.waitKey(1) == ESC:
            return False


def _pulse_and_capture(cv2, cap, estimator, points: list[tuple[int, int]], sw: int, sh: int):
    features, targets = [], []
    for index, (x, y) in enumerate(points):
        start, radius = time.time(), 20.0
        while (elapsed := time.time() - start) <= PULSE_S:  # eyes travel: the dot breathes, nothing is kept
            ok, _ = cap.read()
            if not ok:
                continue
            radius = 15 + 15 * abs(math.sin(2 * math.pi * elapsed))  # eyetrax's pulse radius
            window.show(cv2, WINDOW, screens.calibration_target(sw, sh, (x, y), "pulse", elapsed / PULSE_S,
                                                                index, len(points), radius))
            if cv2.waitKey(1) == ESC:
                return None
        start = time.time()
        while (elapsed := time.time() - start) <= CAPTURE_S:  # capture: keep every open-eyed frame
            ok, frame = cap.read()
            if not ok:
                continue
            window.show(cv2, WINDOW, screens.calibration_target(sw, sh, (x, y), "capture", elapsed / CAPTURE_S,
                                                                index, len(points), radius))
            if cv2.waitKey(1) == ESC:
                return None
            feature, blink = estimator.extract_features(frame)
            if feature is not None and not blink:
                features.append(feature)
                targets.append([x, y])
    return features, targets


def run_9_point_calibration(estimator, camera_index: int = 0) -> None:
    """Drop-in for eyetrax.run_9_point_calibration (same arguments, same result on the estimator)."""
    import cv2
    from eyetrax.calibration.common import compute_grid_points
    from eyetrax.utils.screen import get_screen_size
    from eyetrax.utils.video import open_camera

    sw, sh = get_screen_size()
    cap = open_camera(camera_index)
    window.open_fullscreen(cv2, WINDOW)
    try:
        if not _wait_for_face(cv2, cap, estimator, sw, sh):
            return
        result = _pulse_and_capture(cv2, cap, estimator, compute_grid_points(NINE_POINT_ORDER, sw, sh), sw, sh)
        if result is None:
            return
        features, targets = result
        if features:
            estimator.train(np.array(features), np.array(targets))
    finally:
        cap.release()
        cv2.destroyAllWindows()
