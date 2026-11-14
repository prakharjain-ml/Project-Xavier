"""MotorDriver against MockSerial only (agents never open a real port). Uses short real-time waits."""

import time

from motors.driver import MotorDriver
from motors.mock_serial import MockSerial
from shared.protocol import MotorCommand


def started(*ports, **kwargs):
    """Driver whose port factory hands out the given mocks in order (then None = cannot open)."""
    queue = list(ports)
    driver = MotorDriver(lambda: queue.pop(0) if queue else None, reopen_s=0.05, **kwargs)
    driver.start()
    return driver


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
    assert drive_lines and all(ln.endswith(",80,-80") for ln in drive_lines)
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
