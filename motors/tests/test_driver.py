"""MotorDriver against MockSerial only (agents never open a real port). Uses short real-time waits."""

import time

import pytest

from motors.driver import SLEW_STEP, MotorDriver, looks_like_openbci_dongle
from motors.mock_serial import MockSerial
from shared.protocol import CONTROL_HZ, MAX_SPEED, MotorCommand


def started(*ports, **kwargs):
    """Driver whose port factory hands out the given mocks in order (then None = cannot open)."""
    queue = list(ports)
    driver = MotorDriver(lambda: queue.pop(0) if queue else None, reopen_s=0.05, **kwargs)
    driver.start()
    return driver


def speeds(lines):
    """(left, right) of each written line; an S (stop) line counts as (0, 0)."""
    return [tuple(int(v) for v in ln.split(",")[2:]) if ln.startswith("C,") else (0, 0) for ln in lines]


def wait_until(condition, timeout_s=10.0):
    """Poll instead of sleeping a fixed time, so a loaded machine only makes a test slower, not flaky."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.005)
    return condition()


class ScriptedPort(MockSerial):
    """MockSerial that changes the command at an exact line: `script[n]` is handed to the driver right after
    line number n (counting from 0) has been written. It runs inside the driver's own thread, so the very next
    line is the first one that can show the change, however slow or busy the machine is."""

    def __init__(self, script=None, **kwargs):
        super().__init__(**kwargs)
        self.script, self.driver, self.times = dict(script or {}), None, []

    def write(self, data):
        written = super().write(data)
        self.times.append(time.monotonic())
        action = self.script.get(len(self.times) - 1)
        if action is not None:
            now = time.monotonic()
            self.driver.send(MotorCommand.halt(now) if action == STOP else MotorCommand(*action, False, now))
        return written


STOP = "stop"
NEVER_STALE_S = 3600.0  # these tests send each command once; it must not go stale while the lines are counted


def scripted(*ports, hz=200.0):
    """Fast driver (200 lines a second) on scripted ports; the first port is opened first, then the next."""
    queue = list(ports)
    driver = MotorDriver(lambda: queue.pop(0) if queue else None, hz=hz, stale_s=NEVER_STALE_S, reopen_s=0.01)
    for port in ports:
        port.driver = driver
    driver.start()
    return driver


def lines_after(port, count):
    """The first `count` lines of a port, waiting for them if needed."""
    assert wait_until(lambda: len(port.lines()) >= count), f"only {len(port.lines())} of {count} lines arrived"
    return port.lines()[:count]


def ramp(top, step=SLEW_STEP):
    """The speeds a soft start from zero passes through: step, 2*step, ... and finally `top` itself."""
    return [min(top, step * i) for i in range(1, -(-top // step) + 1)]


def test_slew_step_reaches_full_speed_in_about_two_seconds_at_the_send_rate():
    """About 1 s at the old cap of 150; the cap is 300 since Sun Nov 15 (mock path only: the real chair uses chair.py)."""
    lines_to_full_speed = len(ramp(MAX_SPEED))
    assert 1.6 <= lines_to_full_speed / CONTROL_HZ <= 2.2


def test_drive_command_ramps_up_one_step_per_line_until_it_reaches_the_target():
    # Arrange: full speed ahead is requested right after line 1 (lines 0 and 1 are idle STOP lines)
    port = ScriptedPort({1: (MAX_SPEED, MAX_SPEED)})
    driver = scripted(port)
    expected = ramp(MAX_SPEED)  # 8, 16, ... 144, 150

    # Act
    lines = lines_after(port, 2 + len(expected) + 3)
    driver.stop()

    # Assert: the first drive line is one step, not (150, 150); then one step more per line; then it holds
    assert lines[0].startswith("S,") and lines[1].startswith("S,")
    assert lines[2] == f"C,2,{SLEW_STEP},{SLEW_STEP}"
    assert speeds(lines[2:]) == [(v, v) for v in expected] + [(MAX_SPEED, MAX_SPEED)] * 3


def test_each_wheel_ramps_on_its_own_and_a_target_below_one_step_is_sent_at_once():
    # Arrange: a gentle left curve, and a right wheel that should hardly move
    port = ScriptedPort({0: (60, 5)})
    driver = scripted(port)

    # Act
    lines = lines_after(port, 10)
    driver.stop()

    # Assert
    assert speeds(lines[1:10]) == [(8, 5), (16, 5), (24, 5), (32, 5), (40, 5), (48, 5), (56, 5), (60, 5), (60, 5)]


def test_backward_ramps_up_the_same_way_as_forward():
    port = ScriptedPort({0: (-40, -40)})
    driver = scripted(port)
    lines = lines_after(port, 7)
    driver.stop()
    assert speeds(lines[1:7]) == [(-8, -8), (-16, -16), (-24, -24), (-32, -32), (-40, -40), (-40, -40)]


def test_stop_in_the_middle_of_the_ramp_is_sent_on_the_very_next_line():
    # Arrange: full speed after line 0; STOP after line 5, when the ramp has only reached 40
    port = ScriptedPort({0: (MAX_SPEED, MAX_SPEED), 5: STOP})
    driver = scripted(port)

    # Act
    lines = lines_after(port, 9)
    driver.stop()

    # Assert: no ramp down, no extra drive line: stopping is never delayed
    assert speeds(lines[1:6]) == [(8, 8), (16, 16), (24, 24), (32, 32), (40, 40)]
    assert lines[6] == "S,6"
    assert all(ln.startswith("S,") for ln in lines[6:9])


def test_slowing_down_is_immediate():
    # Arrange: reach (80, 80), then ask for (20, 60)
    port = ScriptedPort({0: (80, 80), 11: (20, 60)})
    driver = scripted(port)

    # Act
    lines = lines_after(port, 14)
    driver.stop()

    # Assert: both wheels drop to the lower speed on the next line
    assert speeds(lines[10:14]) == [(80, 80), (80, 80), (20, 60), (20, 60)]


def test_after_a_stop_the_ramp_starts_again_from_zero():
    # Arrange: ramp to 40, STOP for three lines, then full speed again
    port = ScriptedPort({0: (MAX_SPEED, MAX_SPEED), 5: STOP, 8: (MAX_SPEED, MAX_SPEED)})
    driver = scripted(port)

    # Act
    lines = lines_after(port, 13)
    driver.stop()

    # Assert: the second start begins at one step, not where the first ramp left off (48)
    assert speeds(lines[5:13]) == [(40, 40), (0, 0), (0, 0), (0, 0), (8, 8), (16, 16), (24, 24), (32, 32)]


def test_command_going_stale_stops_at_once_and_the_next_command_ramps_from_zero():
    # Arrange: a normal driver (commands go stale after 0.1 s); control feeds it, goes quiet, comes back
    port = ScriptedPort()
    driver = started(port, stale_s=0.1)
    port.driver = driver
    feed_until = time.monotonic() + 0.5
    while time.monotonic() < feed_until:
        driver.send(MotorCommand(MAX_SPEED, MAX_SPEED, False, time.monotonic()))
        time.sleep(0.01)
    assert wait_until(lambda: port.lines()[-1].startswith("S,"))  # control went quiet: STOP
    quiet_from = len(port.lines())

    # Act
    resume_until = time.monotonic() + 0.3
    while time.monotonic() < resume_until:
        driver.send(MotorCommand(MAX_SPEED, MAX_SPEED, False, time.monotonic()))
        time.sleep(0.01)
    lines = port.lines()
    driver.stop()

    # Assert: whatever the first run reached, the first drive line after the gap is one step
    assert max(speeds(lines[:quiet_from])) > (SLEW_STEP, SLEW_STEP)
    resumed = [pair for pair in speeds(lines[quiet_from:]) if pair != (0, 0)]
    assert resumed and resumed[0] == (SLEW_STEP, SLEW_STEP)


def test_after_a_reconnect_the_ramp_starts_again_from_zero():
    # Arrange: the cable "falls out" after 12 lines, while the command is still full speed ahead
    first = ScriptedPort({0: (MAX_SPEED, MAX_SPEED)}, fail_after_writes=12)
    second = ScriptedPort()
    driver = scripted(first, second)

    # Act
    lines = lines_after(second, 6)
    driver.stop()

    # Assert: the audit saw "C,20,150,150" as the first line on the new port; now it is one step
    assert speeds(first.lines())[-1] == (88, 88)
    assert speeds(lines) == [(8, 8), (16, 16), (24, 24), (32, 32), (40, 40), (48, 48)]


def test_reversal_goes_through_zero_and_then_ramps_the_other_way():
    # Arrange: reach (80, 80) forward, then ask for (80, 80) backward
    port = ScriptedPort({0: (80, 80), 11: (-80, -80)})
    driver = scripted(port)

    # Act
    lines = lines_after(port, 16)
    driver.stop()

    # Assert: one explicit stop line, then a fresh ramp in the new direction
    assert speeds(lines[11:16]) == [(80, 80), (0, 0), (-8, -8), (-16, -16), (-24, -24)]
    assert lines[12] == "S,12"


def test_one_wheel_reversing_goes_through_zero_while_the_other_keeps_its_speed():
    # Arrange: straight ahead at 80, then spin right (left wheel forward, right wheel backward)
    port = ScriptedPort({0: (80, 80), 11: (80, -80)})
    driver = scripted(port)

    # Act
    lines = lines_after(port, 15)
    driver.stop()

    # Assert
    assert speeds(lines[11:15]) == [(80, 80), (80, 0), (80, -8), (80, -16)]


def test_speed_beyond_the_cap_ramps_to_the_cap_and_no_further():
    port = ScriptedPort({0: (400, -400)})
    driver = scripted(port)
    lines = lines_after(port, 1 + len(ramp(MAX_SPEED)) + 3)
    driver.stop()
    assert speeds(lines[1:]) == [(v, -v) for v in ramp(MAX_SPEED)] + [(MAX_SPEED, -MAX_SPEED)] * 3


def test_soft_start_takes_about_a_second_at_the_real_send_rate():
    # Arrange: the driver exactly as the app builds it (20 lines a second), kept fed like control does
    port = ScriptedPort()
    driver = started(port)
    port.driver = driver

    # Act: hold full speed until the port has seen it
    def fed_and_at_full_speed():
        driver.send(MotorCommand(MAX_SPEED, MAX_SPEED, False, time.monotonic()))
        return (MAX_SPEED, MAX_SPEED) in speeds(port.lines())

    reached = wait_until(fed_and_at_full_speed, timeout_s=15.0)
    lines, times = port.lines(), list(port.times)
    driver.stop()

    # Assert: only a LOWER bound on the time. The driver waits 50 ms between lines, so a busy machine can make
    # the ramp slower but never faster; an upper bound would only test how loaded the machine is.
    assert reached
    pairs = speeds(lines)
    full = pairs.index((MAX_SPEED, MAX_SPEED))
    start = max(i for i in range(full) if pairs[i] == (0, 0)) + 1  # first line of the ramp that got there
    assert pairs[start:full + 1] == [(v, v) for v in ramp(MAX_SPEED)]
    assert times[full] - times[start] >= 0.85


@pytest.mark.parametrize("port", [
    "/dev/cu.usbserial-DM00Q7XX",  # the name in our docs
    "/dev/cu.usbserial-DN0096XA",  # other FTDI serial numbers OpenBCI dongles ship with
    "/dev/cu.usbserial-DQ007UBV",
    "/dev/cu.usbserial-D200PMA1",
    "/dev/tty.usbserial-DM00Q7XX",
    "/dev/cu.usbserial-AB0JQ3XY",  # any FTDI-style serial: starts with a letter
    "/dev/serial/by-id/usb-FTDI_FT231X_USB_UART_DM00Q7XX-if00-port0",  # Linux, by-id name
])
def test_ftdi_style_port_names_are_refused_as_a_possible_openbci_dongle(port):
    assert looks_like_openbci_dongle(port) is True


@pytest.mark.parametrize("port", [
    "/dev/cu.usbserial-0001",  # ESP32 with a CP2102 chip
    "/dev/cu.usbserial-1410",  # ESP32 with a CH340 chip
    "/dev/cu.usbserial-110",
    "/dev/cu.SLAB_USBtoUART",  # CP210x with the Silicon Labs driver
    "/dev/cu.wchusbserial1410",  # CH340 with the WCH driver
    "/dev/cu.wchusbserial-1410",
    "/dev/cu.usbmodem1101",  # ESP32 with native USB
])
def test_usual_esp32_port_names_are_accepted(port):
    assert looks_like_openbci_dongle(port) is False


@pytest.mark.parametrize("port", ["COM3", "COM5", "/dev/ttyUSB0"])
def test_names_that_say_nothing_about_the_device_are_not_refused(port):
    # Windows COM numbers and Linux ttyUSB numbers are the same for a dongle and an ESP32: the name cannot
    # tell them apart, and the team's bench tests reach the bridge on COM4/COM5. This documents the gap.
    assert looks_like_openbci_dongle(port) is False


def test_sends_stop_lines_at_20hz_when_idle():
    port = MockSerial()
    driver = started(port)
    time.sleep(0.5)
    lines = port.lines()  # count before stop(): stop() adds its own final STOP lines
    driver.stop()
    assert 7 <= len(lines) <= 13, len(lines)  # ~10 lines in 0.5 s at 20 Hz
    assert all(line.startswith("S,") for line in lines)


def test_latest_fresh_command_is_sent_with_increasing_seq():
    port = MockSerial()
    driver = started(port)
    driver.send(MotorCommand(50, 50, False, time.monotonic()))
    driver.send(MotorCommand(80, -80, False, time.monotonic()))  # latest wins
    time.sleep(0.12)
    driver.send(MotorCommand(80, -80, False, time.monotonic()))
    time.sleep(0.12)
    driver.stop()
    drive_lines = [ln for ln in port.lines() if ln.startswith("C,")]
    # The wheels ramp up (soft start), so check the direction: (50, 50) would make the right wheel positive.
    assert drive_lines and all(left > 0 > right for left, right in speeds(drive_lines))
    seqs = [int(ln.split(",")[1]) for ln in port.lines()]
    assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs)


def test_stale_command_becomes_stop():
    port = MockSerial()
    driver = started(port, stale_s=0.1)
    driver.send(MotorCommand(80, 80, False, time.monotonic()))
    time.sleep(0.4)  # control stopped feeding commands
    lines = port.lines()  # before stop(): its own final STOP lines would make this test pass vacuously
    driver.stop()
    assert any(ln.startswith("C,") for ln in lines[:2])  # it did drive while the command was fresh
    assert all(ln.startswith("S,") for ln in lines[-4:])  # then fell back to STOP once it went stale


def test_stop_sends_final_stop_lines():
    port = MockSerial()
    driver = started(port)
    driver.send(MotorCommand(80, 80, False, time.monotonic()))
    time.sleep(0.1)
    driver.stop()
    assert all(ln.startswith("S,") for ln in port.lines()[-3:])


def test_reads_bridge_distance_and_state():
    port = MockSerial(replies=["D,40,OBSTACLE\n", "D,35,OBSTACLE\n"])
    driver = started(port)
    time.sleep(0.15)
    status = driver.status()
    driver.stop()
    assert status.connected and status.bridge.distance_cm == 35 and status.bridge.state == "OBSTACLE"
    assert driver.distance_cm() == 35


def test_old_distance_is_not_reported():
    port = MockSerial(replies=["D,40,OK\n"])
    driver = started(port, bridge_stale_s=0.1)
    time.sleep(0.3)  # no new D lines since the first one
    assert driver.distance_cm() is None
    driver.stop()


def test_serial_failure_does_not_crash_and_reconnects():
    broken = MockSerial(fail_after_writes=2)
    healthy = MockSerial()
    driver = started(broken, healthy)
    time.sleep(0.5)
    status = driver.status()
    driver.stop()
    assert status.connected  # reopened with the second port
    assert len(broken.lines()) == 2 and len(healthy.lines()) > 3


def test_no_port_available_stays_disconnected_without_raising():
    driver = started()  # factory returns None every time
    time.sleep(0.2)
    assert not driver.status().connected
    driver.stop()


def test_driver_skips_hash_info_lines_and_keeps_reading_status():
    port = MockSerial(replies=["# LEFT board OK, RIGHT board NOT FOUND\n", "D,42,OK\n", "# info\n"])
    driver = started(port)
    time.sleep(0.15)
    status = driver.status()
    driver.stop()
    assert status.bridge.distance_cm == 42 and status.bridge.state == "OK"
