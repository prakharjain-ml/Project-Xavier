"""Line protocol between laptop and ESP32 bridge (docs/INTERFACES.md). Pure functions, no port."""

import pytest

from motors.bridge_protocol import BridgeStatus, encode_command, parse_status
from shared.protocol import MAX_SPEED, MotorCommand


def test_drive_command_line():
    assert encode_command(MotorCommand(80, -80, False, 0.0), seq=7) == "C,7,80,-80\n"


def test_stop_command_line_when_stop_flag_set():
    assert encode_command(MotorCommand(150, 150, True, 0.0), seq=3) == "S,3\n"  # stop overrides speeds


def test_zero_speeds_send_explicit_stop():
    assert encode_command(MotorCommand(0, 0, False, 0.0), seq=0) == "S,0\n"


def test_speeds_are_clamped_again():
    assert encode_command(MotorCommand(5000, -5000, False, 0.0), seq=1) == f"C,1,{MAX_SPEED},{-MAX_SPEED}\n"


@pytest.mark.parametrize("line, expected", [
    ("D,37,OBSTACLE\n", BridgeStatus(37, "OBSTACLE")),
    ("D,-1,OK", BridgeStatus(-1, "OK")),
    ("D,120,WATCHDOG\r\n", BridgeStatus(120, "WATCHDOG")),
])
def test_parse_valid_status(line, expected):
    assert parse_status(line) == expected


@pytest.mark.parametrize("line", ["", "garbage", "D,abc,OK", "D,10", "D,10,DANCING", "X,1,OK", "D,10,OK,extra"])
def test_parse_rejects_malformed(line):
    assert parse_status(line) is None
