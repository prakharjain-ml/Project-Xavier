"""app.py: keyboard stands in for the decoder; the real state machine and driver logic run. No real port."""

import os
import re

os.environ["SDL_VIDEODRIVER"] = "dummy"
os.environ["SDL_AUDIODRIVER"] = "dummy"

import pygame  # noqa: E402
import pytest  # noqa: E402

from app import KeyboardIntentSource, control_tick, looks_like_openbci_dongle, main  # noqa: E402
from control.state_machine import ControllerState  # noqa: E402
from shared.protocol import CONTROL_HZ, DWELL_S, MAX_SPEED, State, Target  # noqa: E402


class FakeDriver:
    def __init__(self, distance=None):
        self.sent, self.distance = [], distance

    def send(self, command):
        self.sent.append(command)

    def distance_cm(self):
        return self.distance


def key(event_type, k):
    return pygame.event.Event(event_type, key=k)


def run_ticks(source, driver, state, start, seconds):
    now = start
    for i in range(int(seconds * CONTROL_HZ)):
        now = start + i / CONTROL_HZ
        state, _status = control_tick(source, driver, state, now)
    return state, now


def test_holding_up_moves_forward_only_after_dwell_then_release_stops():
    source, driver = KeyboardIntentSource(), FakeDriver()
    source.on_event(key(pygame.KEYDOWN, pygame.K_UP))
    state, now = run_ticks(source, driver, ControllerState(), 0.0, DWELL_S - 0.1)
    assert all(c.stop for c in driver.sent)  # still dwelling: no motion yet
    state, now = run_ticks(source, driver, state, now + 0.05, 0.5)
    assert state.state == State.MOVING
    assert (driver.sent[-1].left, driver.sent[-1].right, driver.sent[-1].stop) == (MAX_SPEED, MAX_SPEED, False)
    source.on_event(key(pygame.KEYUP, pygame.K_UP))
    state, _ = control_tick(source, driver, state, now + 0.05)
    assert state.state == State.STOPPED and driver.sent[-1].stop  # release -> stop on the very next tick


def test_two_arrows_at_once_is_ambiguous_and_never_moves():
    source, driver = KeyboardIntentSource(), FakeDriver()
    source.on_event(key(pygame.KEYDOWN, pygame.K_UP))
    source.on_event(key(pygame.KEYDOWN, pygame.K_LEFT))
    run_ticks(source, driver, ControllerState(), 0.0, 3.0)
    assert all(c.stop for c in driver.sent)


def test_space_is_estop_and_r_rearms_after_quiet_period():
    source, driver = KeyboardIntentSource(), FakeDriver()
    source.on_event(key(pygame.KEYDOWN, pygame.K_SPACE))
    state, _ = control_tick(source, driver, ControllerState(), 10.0)
    assert state.state == State.E_STOP
    source.on_event(key(pygame.KEYDOWN, pygame.K_r))
    state, _ = control_tick(source, driver, state, 10.1)  # too soon: stop still counts as active
    assert state.state == State.E_STOP
    source.on_event(key(pygame.KEYDOWN, pygame.K_r))
    state, _ = control_tick(source, driver, state, 11.0)
    assert state.state == State.STOPPED


def test_forward_blocked_by_bridge_distance():
    source, driver = KeyboardIntentSource(), FakeDriver(distance=30)
    source.on_event(key(pygame.KEYDOWN, pygame.K_UP))
    run_ticks(source, driver, ControllerState(), 0.0, 3.0)
    assert all(c.stop for c in driver.sent)


@pytest.mark.parametrize("port, dongle", [
    ("/dev/cu.usbserial-DM00Q7XX", True),
    ("/dev/cu.usbserial-0001", False),
    ("/dev/cu.SLAB_USBtoUART", False),
])
def test_openbci_dongle_port_is_recognised(port, dongle):
    assert looks_like_openbci_dongle(port) is dongle


def test_refuses_openbci_dongle_port():
    assert main(["--keyboard", "--serial", "/dev/cu.usbserial-DM00Q7XX", "--seconds", "0.2"]) == 2


def test_headless_mock_run_streams_stop_lines(capsys):
    assert main(["--keyboard", "--mock", "--windowed", "--seconds", "1.5"], start_events=["space"]) == 0
    out = capsys.readouterr().out
    lines = int(re.search(r"bridge_lines=(\d+)", out).group(1))
    assert 15 <= lines <= 40  # ~20 lines/s while idle, all STOP
    assert "final_state=STOPPED" in out


def test_end_to_end_held_forward_reaches_the_port_as_drive_lines_after_dwell(monkeypatch):
    """Full app loop (screen + control thread + driver thread) with FORWARD held and a recording fake port."""
    import app
    from motors.mock_serial import MockSerial

    ports = []

    class RecordingMock(MockSerial):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            ports.append(self)

    real_snapshot = app.KeyboardIntentSource.snapshot

    def forward_held(self, now):
        self._held = frozenset({Target.FWD})  # as if the rider holds the Up arrow the whole time
        return real_snapshot(self, now)

    monkeypatch.setattr(app, "MockSerial", RecordingMock)
    monkeypatch.setattr(app.KeyboardIntentSource, "snapshot", forward_held)
    assert main(["--keyboard", "--mock", "--windowed", "--seconds", "3"], start_events=["space"]) == 0
    lines = ports[0].lines()
    first_drive = next(i for i, line in enumerate(lines) if line.startswith("C,"))
    assert lines[first_drive].endswith(f",{MAX_SPEED},{MAX_SPEED}")  # forward at the speed cap
    assert first_drive >= 25  # ~1.5 s of STOP lines at 20 Hz first: the dwell was respected
    assert all(line.startswith("S,") for line in lines[-5:])  # app exit sends explicit STOP


# ---------------------------------------------------------------- gaze mode
import queue as _queue  # noqa: E402
import threading as _threading  # noqa: E402
import time as _time  # noqa: E402

from vision.gaze import GazeSample  # noqa: E402


def _gaze_source_with(*samples):
    from app import GazeIntentSource

    q = _queue.Queue()
    for s in samples:
        q.put(s)
    return GazeIntentSource(q)


@pytest.mark.parametrize("point, expected", [
    ((0.5, 0.1), Target.FWD), ((0.1, 0.5), Target.LEFT), ((0.9, 0.5), Target.RIGHT), ((0.5, 0.9), Target.BACK),
    ((0.5, 0.5), Target.NONE),  # resting in the centre selects nothing
])
def test_gaze_regions_map_to_targets(point, expected):
    source = _gaze_source_with(GazeSample(point, False, True, 10.0))
    assert source.snapshot(10.05).intent.target == expected


def test_stale_or_missing_gaze_is_none():
    assert _gaze_source_with(GazeSample((0.5, 0.1), False, True, 10.0)).snapshot(11.0).intent.target == Target.NONE
    assert _gaze_source_with(GazeSample(None, True, True, 10.0)).snapshot(10.05).intent.target == Target.NONE
    assert _gaze_source_with().snapshot(10.0).intent.target == Target.NONE


def test_gaze_mode_space_is_estop_and_arrow_keys_do_nothing():
    source = _gaze_source_with()
    source.on_event(key(pygame.KEYDOWN, pygame.K_UP))  # keyboard must not drive in gaze mode
    assert source.snapshot(1.0).intent.target == Target.NONE
    source.on_event(key(pygame.KEYDOWN, pygame.K_SPACE))
    assert source.snapshot(1.1).stop_requests


def test_gaze_mode_refuses_to_start_without_calibration(tmp_path):
    assert main(["--gaze", "--mock", "--calibration", str(tmp_path / "missing.json"), "--seconds", "0.2"]) == 2


def test_end_to_end_gaze_on_forward_arrow_drives_after_dwell(monkeypatch, tmp_path):
    """Full app with a fake gaze process that keeps reporting the top (FORWARD) region."""
    import app
    from motors.mock_serial import MockSerial

    ports, stop_fake = [], _threading.Event()

    class RecordingMock(MockSerial):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            ports.append(self)

    def fake_gaze_process(_camera, _calibration):
        q = _queue.Queue(maxsize=1)

        def feed():
            while not stop_fake.is_set():
                app.offer_latest(q, GazeSample((0.5, 0.1), False, True, _time.monotonic()))
                stop_fake.wait(0.05)

        _threading.Thread(target=feed, daemon=True).start()
        return None, q, stop_fake

    calibration = tmp_path / "cal.json"
    calibration.write_text("{}")
    monkeypatch.setattr(app, "MockSerial", RecordingMock)
    monkeypatch.setattr(app, "start_gaze_process", fake_gaze_process)
    assert main(["--gaze", "--mock", "--windowed", "--seconds", "3", "--calibration", str(calibration)],
                start_events=["space"]) == 0
    lines = ports[0].lines()
    first_drive = next(i for i, line in enumerate(lines) if line.startswith("C,"))
    assert lines[first_drive].endswith(f",{MAX_SPEED},{MAX_SPEED}")
    assert first_drive >= 25  # the 1.5 s dwell still applies to gaze
