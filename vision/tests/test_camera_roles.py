"""Choosing the eye camera and the forward camera by what they see, not by their (shuffling) index."""

import pytest

from vision.camera_roles import CameraProbe, assign_roles


def probe(index, face, width=1920):
    return CameraProbe(index=index, sees_face=face, width=width, height=1080)


def test_face_camera_is_eye_and_the_other_is_forward():
    assert assign_roles([probe(0, False), probe(1, True)]) == (1, 0)
    assert assign_roles([probe(0, True), probe(1, False)]) == (0, 1)


def test_only_one_camera_explains_that_the_pixel_is_missing():
    with pytest.raises(RuntimeError, match="only one camera"):
        assign_roles([probe(0, True)])


def test_no_face_anywhere_asks_the_rider_to_sit_in_view():
    with pytest.raises(RuntimeError, match="no camera sees a face"):
        assign_roles([probe(0, False), probe(1, False)])


def test_two_cameras_seeing_faces_is_ambiguous():
    with pytest.raises(RuntimeError, match="point the forward camera away"):
        assign_roles([probe(0, True), probe(1, True)])
