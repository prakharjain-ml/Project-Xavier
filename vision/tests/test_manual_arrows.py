"""Manual gaze arrows: looking at an arrow drives that way at once; looking elsewhere does not."""

import cv2
import numpy as np

from shared.protocol import MAX_SPEED, Target
from vision.manual_arrows import ARROW_REGIONS, ARROW_WHEELS, arrow_at, draw_arrows


def _centre(target):
    x1, y1, x2, y2 = ARROW_REGIONS[target]
    return ((x1 + x2) / 2, (y1 + y2) / 2)


def test_looking_at_each_arrow_picks_it_and_the_middle_or_no_gaze_picks_nothing():
    for target in ARROW_REGIONS:
        assert arrow_at(_centre(target)) == target
    assert arrow_at((0.5, 0.5)) is None
    assert arrow_at(None) is None


def test_arrow_wheels_forward_back_full_speed_and_turns_spin_in_place():
    assert ARROW_WHEELS[Target.FWD] == (MAX_SPEED, MAX_SPEED)
    assert ARROW_WHEELS[Target.BACK] == (-MAX_SPEED, -MAX_SPEED)
    left, right = ARROW_WHEELS[Target.RIGHT]
    assert left > 0 > right and left == -right
    left, right = ARROW_WHEELS[Target.LEFT]
    assert left < 0 < right and right == -left


def test_drawing_leaves_the_input_alone_and_changes_the_picture():
    canvas = np.zeros((800, 1280, 3), np.uint8)
    out = draw_arrows(cv2, canvas, 46, 682, Target.FWD, (180, 170, 0), (248, 232, 8))
    assert canvas.sum() == 0 and out.sum() > 0


def test_manual_tick_sends_the_arrow_wheels_without_any_confirm():
    from control.state_machine import ControllerState
    from vision.object_select import manual_tick

    class Driver:
        sent = []

        def send(self, command):
            self.sent.append(command)

    ctrl, note = manual_tick(Target.FWD, Driver(), ControllerState(), 1.0)
    command = Driver.sent[-1]
    assert not command.stop and (command.left, command.right) == ARROW_WHEELS[Target.FWD]
    assert ctrl.state.value == "MOVING" and "MANUAL forward" in note
