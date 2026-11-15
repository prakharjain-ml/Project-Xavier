"""Find which camera is which by what it sees. macOS reorders camera numbers whenever the Pixel (re)connects,
so hard-coded indices broke a live test (the eye tracker opened a camera that no longer existed).

Eye camera = the camera with the BIGGEST face in view: the rider sits 50-70 cm from the laptop camera, so their
face is far larger there than anyone's is in the forward camera. Forward camera = the other one. The forward
camera is allowed to see faces: at a demo there are always people in the room. (The first version said "the
camera that sees a face is the eye camera"; on Sat Nov 14 the Pixel faced a teammate across the table and was
taken for the eye camera, so objects were detected on the rider's own face.)
"""

from __future__ import annotations

import os
from dataclasses import dataclass

MAX_CAMERAS = 4
WARMUP_FRAMES = 8  # the first frames from a just-opened camera are often dark
MAX_FACES = 4  # look for several faces per camera and keep the widest: a room has more than one person
CLEARLY_BIGGER = 1.4  # the rider's face must be this many times wider than any face in the other camera


@dataclass(frozen=True)
class CameraProbe:
    index: int
    sees_face: bool
    width: int
    height: int
    face_width: float = 0.0  # widest face in view, as a fraction of the picture's width (0 = no face)


def assign_roles(probes: list[CameraProbe]) -> tuple[int, int]:
    """Returns (eye_camera, forward_camera) or raises RuntimeError with a fix the rider can act on."""
    if len(probes) < 2:
        raise RuntimeError("only one camera found: reconnect the Pixel in Webcam mode and keep it unlocked")
    by_face = sorted(probes, key=lambda p: p.face_width, reverse=True)  # biggest face first
    eye, runner_up = by_face[0], by_face[1]
    if eye.face_width <= 0:
        raise RuntimeError("no camera sees a face: sit in front of the laptop camera, with light on your face")
    if runner_up.face_width > 0 and eye.face_width < CLEARLY_BIGGER * runner_up.face_width:
        raise RuntimeError("two cameras see a face of about the same size, so the eye camera cannot be told "
                           "apart: sit closer to the laptop camera, or pass --eye-camera N --source M")
    forward = by_face[-1]  # the smallest (or no) face: the camera looking at the room
    return eye.index, forward.index


def forward_camera(probes: list[CameraProbe]) -> int:
    """For programs with no rider at the screen (the mouse preview): the camera with the smallest face in view,
    lowest number on a tie (macOS lists the plugged-in phone before the built-in camera)."""
    if not probes:
        raise RuntimeError("no camera found: reconnect the Pixel in Webcam mode and keep it unlocked")
    return min(probes, key=lambda p: (p.face_width, p.index)).index


def probe_cameras(model_path: str | None = None) -> list[CameraProbe]:
    """Open each camera index once and check for a face (MediaPipe). Run in a cv2 process only (not pygame)."""
    import cv2
    import mediapipe as mp

    from vision.gaze_tracker import MODEL_PATH

    vision = mp.tasks.vision
    options = vision.FaceLandmarkerOptions(
        base_options=mp.tasks.BaseOptions(model_asset_path=os.path.expanduser(model_path or MODEL_PATH)),
        num_faces=MAX_FACES)
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
            faces = landmarker.detect(image).face_landmarks
            # Landmark x runs 0..1 across the picture, so max - min is the face's width as a share of the picture.
            widest = max((max(p.x for p in face) - min(p.x for p in face) for face in faces), default=0.0)
            probes.append(CameraProbe(index, bool(faces), frame.shape[1], frame.shape[0], float(widest)))
    return probes
