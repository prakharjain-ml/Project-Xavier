"""EyeTrax adapter: screen pixels -> our normalized GazeSample, with our blink rule. No EyeTrax needed."""

import pytest

from vision.gaze import BlinkState
from vision.gaze_tracker_eyetrax import to_sample

SCREEN = (1470, 956)


def test_pixels_become_screen_fractions():
    _, s = to_sample((735, 239), SCREEN, face=True, blink=False, state=BlinkState(), now=1.0)
    assert s.point == pytest.approx((0.5, 0.25)) and s.face and not s.closed and s.t == 1.0


def test_off_screen_predictions_are_clamped():
    _, s = to_sample((-50, 2000), SCREEN, face=True, blink=False, state=BlinkState(), now=1.0)
    assert s.point == (0.0, 1.0)


def test_short_blink_holds_long_closure_drops():
    state, _ = to_sample((735, 239), SCREEN, face=True, blink=False, state=BlinkState(), now=0.0)
    state, held = to_sample(None, SCREEN, face=True, blink=True, state=state, now=0.2)
    assert held.closed and held.point == pytest.approx((0.5, 0.25))
    _, dropped = to_sample(None, SCREEN, face=True, blink=True, state=state, now=0.8)
    assert dropped.point is None


def test_no_face_is_no_gaze():
    _, s = to_sample(None, SCREEN, face=False, blink=False, state=BlinkState(), now=2.0)
    assert not s.face and s.point is None


def test_backend_choice_and_tracker_command(monkeypatch):
    from vision import gaze_link

    monkeypatch.setenv("GAZE_BACKEND", "builtin")
    assert gaze_link.gaze_backend() == "builtin"
    monkeypatch.setenv("GAZE_BACKEND", "eyetrax")
    assert gaze_link.gaze_backend() == "eyetrax"
    cmd = gaze_link.tracker_command("eyetrax", "auto", "unused.json", 5555)
    assert cmd[0].endswith("venvs/eyetrax/bin/python") and "vision.gaze_tracker_eyetrax" in cmd and "5555" in cmd
    assert "vision.gaze_tracker" in gaze_link.tracker_command("builtin", 0, "cal.json", 5555)
