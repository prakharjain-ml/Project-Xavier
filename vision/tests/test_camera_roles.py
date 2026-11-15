"""Which camera watches the rider's eyes and which watches the room (vision/camera_roles.py)."""

import pytest

from vision.camera_roles import CameraProbe, assign_roles, forward_camera


def probe(index, face_width=0.0):
    """face_width = widest face in view as a fraction of the picture (0 = no face)."""
    return CameraProbe(index=index, sees_face=face_width > 0, width=1920, height=1080, face_width=face_width)


def test_the_camera_with_a_face_is_the_eye_camera_and_the_other_is_forward():
    assert assign_roles([probe(0), probe(1, 0.25)]) == (1, 0)
    assert assign_roles([probe(0, 0.25), probe(1)]) == (0, 1)


def test_people_in_the_forward_camera_do_not_confuse_the_roles():
    """Sat Nov 14: the Pixel (camera 0) faced a teammate across the table (face 11% of the picture) while the
    rider sat at the laptop camera (23%). The old rule took the Pixel for the eye camera."""
    assert assign_roles([probe(0, 0.11), probe(1, 0.23)]) == (1, 0)
    assert assign_roles([probe(0, 0.23), probe(1, 0.11)]) == (0, 1)


def test_one_camera_is_not_enough():
    with pytest.raises(RuntimeError, match="only one camera"):
        assign_roles([probe(0, 0.25)])


def test_no_face_anywhere_is_an_error_the_rider_can_fix():
    with pytest.raises(RuntimeError, match="no camera sees a face"):
        assign_roles([probe(0), probe(1)])


def test_two_faces_of_about_the_same_size_are_refused_rather_than_guessed():
    with pytest.raises(RuntimeError, match="about the same size"):
        assign_roles([probe(0, 0.20), probe(1, 0.22)])


def test_forward_camera_for_the_mouse_preview_is_the_one_with_the_smallest_face():
    assert forward_camera([probe(0, 0.11), probe(1, 0.23)]) == 0
    assert forward_camera([probe(0, 0.25), probe(1)]) == 1
    assert forward_camera([probe(0), probe(1)]) == 0  # nobody in view: the plugged-in phone comes first on macOS
    with pytest.raises(RuntimeError, match="no camera found"):
        forward_camera([])
