"""Find which camera is which by what it sees. macOS reorders camera numbers whenever the Pixel (re)connects,
so hard-coded indices broke a live test (the eye tracker opened a camera that no longer existed).

Eye camera = the camera that sees the rider's face. Forward camera = another camera that does not.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

MAX_CAMERAS = 4
WARMUP_FRAMES = 8  # the first frames from a just-opened camera are often dark


@dataclass(frozen=True)
class CameraProbe:
    index: int
    sees_face: bool
    width: int
    height: int


def assign_roles(probes: list[CameraProbe]) -> tuple[int, int]:
    """Returns (eye_camera, forward_camera) or raises RuntimeError with a fix the rider can act on."""
    if len(probes) < 2:
        raise RuntimeError("only one camera found: reconnect the Pixel in Webcam mode and keep it unlocked")
    faces = [p for p in probes if p.sees_face]
    if not faces:
        raise RuntimeError("no camera sees a face: sit in front of the laptop camera, with light on your face")
    if len(faces) > 1:
        raise RuntimeError("two cameras see a face: point the forward camera away from people at the screen")
    others = [p for p in probes if not p.sees_face]
    return faces[0].index, others[0].index


def probe_cameras(model_path: str | None = None) -> list[CameraProbe]:
    """Open each camera index once and check for a face (MediaPipe). Run in a cv2 process only (not pygame)."""
    import cv2
    import mediapipe as mp

    from vision.gaze_tracker import MODEL_PATH

    vision = mp.tasks.vision
    options = vision.FaceLandmarkerOptions(
        base_options=mp.tasks.BaseOptions(model_asset_path=os.path.expanduser(model_path or MODEL_PATH)), num_faces=1)
    probes = []
    with vision.FaceLandmarker.create_from_options(options) as landmarker:
        for index in range(MAX_CAMERAS):
            capture = cv2.VideoCapture(index)
            frame = None
            for _ in range(WARMUP_FRAMES):
                ok, frame = capture.read()
            capture.release()
            if frame is None:
                continue
            small = cv2.resize(frame, (640, int(640 * frame.shape[0] / frame.shape[1])))
            image = mp.Image(image_format=mp.ImageFormat.SRGB, data=cv2.cvtColor(small, cv2.COLOR_BGR2RGB))
            probes.append(CameraProbe(index, bool(landmarker.detect(image).face_landmarks),
                                      frame.shape[1], frame.shape[0]))
    return probes
