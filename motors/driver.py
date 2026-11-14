"""Laptop-side motor driver: the messenger between the safety state machine and the ESP32 bridge.

20 times a second it sends the newest MotorCommand down the USB cable as one protocol line, and reads back the
bridge's distance/state lines. Anything wrong (no fresh command, unplugged cable, no port) means it sends STOP
or nothing at all, and the ESP32's own 200 ms watchdog then stops the wheels.

Soft start: a wheel's speed may grow by at most SLEW_STEP per line, so the chair eases off from standstill
(also after any stop and after a reconnect) instead of jumping to the planner's speed. Stops are never slowed.

It never chooses a port itself: the caller passes `open_port`. Auto-detecting is dangerous here because the
OpenBCI dongle also appears as /dev/cu.usbserial-*, and motor lines must never go to the EEG board.
Agents test this only with MockSerial; a human runs it with a real port (rules/50-motors.mdc).
"""

from __future__ import annotations

import logging
import re
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from motors.bridge_protocol import BridgeStatus, clamp_speed, encode_command, parse_status
from shared.protocol import CONTROL_HZ, MotorCommand

log = logging.getLogger("motors.driver")

BAUD = 115200
COMMAND_STALE_S = 0.2  # no new command from control for this long -> send STOP (control runs every 50 ms)
BRIDGE_STALE_S = 0.5  # distance older than this is treated as unknown
REOPEN_S = 1.0  # retry opening a lost port this often
FINAL_STOP_LINES = 5  # stop lines sent when the driver shuts down
# Soft start: the most a wheel's speed may GROW per line sent. Lines go out CONTROL_HZ = 20 times a second and the
# speed cap is 150, so 8 per line takes 19 lines, about 0.95 s, from standstill to the cap (and 13 lines, 0.65 s,
# to the planner's top of about 101). Slowing down and stopping are never limited.
SLEW_STEP = 8

# The OpenBCI dongle has an FTDI chip. macOS names an FTDI port after the chip's serial number, which starts
# with a letter: usbserial-DM00Q7XX, -DN0096XA, -DQ007UBV, -D200PMA1. The usual ESP32 boards have a CP210x or
# CH340 chip, and macOS names those with digits (usbserial-0001, usbserial-1410) or with the driver's own name
# (SLAB_USBtoUART, wchusbserial1410, usbmodem1101).
# What this can tell apart: an FTDI-style name from those ESP32 names, on macOS (and Linux /dev/serial/by-id).
# What it cannot: Windows "COM3" and Linux "/dev/ttyUSB0" say nothing about the device, so they pass, and
# an ESP32 board that happens to have an FTDI chip, or a serial number starting with a letter, is refused.
# It is a guard against picking the wrong line of `ls /dev/cu.*`, not proof of what is plugged in.
_FTDI_STYLE_PORT = re.compile(r"usbserial-[A-Za-z]|FTDI", re.IGNORECASE)


def looks_like_openbci_dongle(port: str) -> bool:
    """True if the port NAME looks like an FTDI adapter, which is what the OpenBCI dongle is. Motor lines must
    never go to the EEG board, so callers refuse such a port. See the comment above for what a name can show."""
    return _FTDI_STYLE_PORT.search(port) is not None


def _slew_wheel(sent: int, target: int, step: int) -> int:
    """Next speed for one wheel, given the speed on the previous line (`sent`) and the speed now asked for."""
    if target == 0 or sent * target < 0:
        # Stopping is immediate. A reversal (the signs differ, so the product is negative) also puts this wheel
        # at zero for one line; the next line then starts the ramp in the new direction from zero.
        return 0
    if abs(target) <= abs(sent) + step:
        return target  # slowing down, or within one step of the target: send it as asked
    return sent + step if target > 0 else sent - step  # speeding up: one step further from zero


def slew_limited(command: MotorCommand, sent: tuple[int, int], step: int = SLEW_STEP) -> MotorCommand:
    """Soft start: `command` with each wheel allowed to speed up by at most `step` beyond `sent`, the (left,
    right) speeds on the previous line. A stop passes through untouched. Returns a new command."""
    if command.stop:
        return command
    left = _slew_wheel(sent[0], clamp_speed(command.left), step)
    right = _slew_wheel(sent[1], clamp_speed(command.right), step)
    return MotorCommand(left, right, False, command.t)


def open_serial(port_name: str) -> Any:
    """HUMAN-RUN PATH ONLY: open the ESP32's USB serial port. Non-blocking reads; short write timeout."""
    import serial  # pyserial; imported here so tests never touch it

    return serial.Serial(port_name, BAUD, timeout=0, write_timeout=0.05)


@dataclass(frozen=True)
class DriverStatus:
    connected: bool
    bridge: BridgeStatus | None  # newest valid line from the bridge
    bridge_age_s: float | None  # seconds since that line
    lines_sent: int


class MotorDriver:
    def __init__(self, open_port: Callable[[], Any], hz: float = CONTROL_HZ, stale_s: float = COMMAND_STALE_S,
                 bridge_stale_s: float = BRIDGE_STALE_S, reopen_s: float = REOPEN_S) -> None:
        self._open_port, self._period = open_port, 1.0 / hz
        self._stale_s, self._bridge_stale_s, self._reopen_s = stale_s, bridge_stale_s, reopen_s
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="motor-driver", daemon=True)
        self._command: MotorCommand | None = None
        self._bridge: tuple[BridgeStatus, float] | None = None
        self._port: Any = None
        self._seq = 0
        self._sent_speeds = (0, 0)  # (left, right) on the newest line written: where the soft-start ramp stands
        self._lines_sent = 0
        self._rx = b""

    # ---- called by the app (any thread) ----
    def start(self) -> None:
        self._thread.start()

    def send(self, command: MotorCommand) -> None:
        """Hand over the newest command. It is written on the next 50 ms tick; older ones are dropped."""
        with self._lock:
            self._command = command

    def status(self) -> DriverStatus:
        with self._lock:
            bridge = self._bridge
            return DriverStatus(self._port is not None, bridge[0] if bridge else None,
                                time.monotonic() - bridge[1] if bridge else None, self._lines_sent)

    def distance_cm(self) -> int | None:
        """Newest bridge distance if fresh, else None (unknown). -1 means nothing in range."""
        status = self.status()
        if status.bridge is None or status.bridge_age_s is None or status.bridge_age_s > self._bridge_stale_s:
            return None
        return status.bridge.distance_cm

    def stop(self) -> None:
        """Stop the thread, then send a few explicit STOP lines (best effort) and close the port."""
        self._stop.set()
        self._thread.join(timeout=1.0)
        for _ in range(FINAL_STOP_LINES):
            if not self._write(MotorCommand.halt(time.monotonic())):
                break
        self._close()

    # ---- driver thread ----
    def _run(self) -> None:
        next_open = 0.0
        while not self._stop.is_set():
            now = time.monotonic()
            if self._port is None and now >= next_open:
                next_open = now + self._reopen_s
                self._try_open()
            try:
                if self._port is not None:
                    self._write(self._current_command(now))
                    self._read_replies()
            except Exception:  # a bug here must not kill the thread: log it, drop the port, retry next tick
                log.exception("driver tick failed; closing port")
                self._close()
            self._stop.wait(self._period)  # this thread may wait; it never blocks control or the screen

    def _current_command(self, now: float) -> MotorCommand:
        with self._lock:
            command = self._command
        if command is None or now - command.t > self._stale_s:
            return MotorCommand.halt(now)  # control went quiet: default is STOP
        return command

    def _try_open(self) -> None:
        try:
            port = self._open_port()
        except OSError as error:  # pyserial's SerialException is an OSError
            log.warning("could not open bridge port: %s", error)
            return
        if port is not None:
            with self._lock:
                self._port, self._rx = port, b""
            log.info("bridge port open")

    def _write(self, command: MotorCommand) -> bool:
        port = self._port
        if port is None:
            return False
        # Every line passes through here, so the soft start cannot be bypassed. It only changes the speeds in a
        # line: it never holds a line back, and a STOP goes out exactly as before.
        command = slew_limited(command, self._sent_speeds)
        try:
            port.write(encode_command(command, self._seq).encode())
        except OSError as error:
            log.error("bridge write failed (%s): port closed; ESP32 watchdog stops the wheels", error)
            self._close()
            return False
        with self._lock:
            self._seq += 1
            self._lines_sent += 1
        # After a stop line the ramp starts again from zero, whatever speed the wheels had before it.
        self._sent_speeds = (0, 0) if command.stop else (command.left, command.right)
        return True

    def _read_replies(self) -> None:
        port = self._port
        if port is None:  # the write just failed and closed it; reading now would crash the thread
            return
        try:
            waiting = port.in_waiting
            data = port.read(waiting) if waiting else b""
        except OSError as error:
            log.error("bridge read failed (%s)", error)
            self._close()
            return
        self._rx += data
        *complete, self._rx = self._rx.split(b"\n")  # keep a partial last line for the next tick
        for raw in complete:
            parsed = parse_status(raw.decode(errors="ignore"))
            if parsed is not None:
                with self._lock:
                    self._bridge = (parsed, time.monotonic())

    def _close(self) -> None:
        # The port is gone, so the ESP32 watchdog stops the wheels. Whatever port opens next starts the ramp
        # from zero: a reconnect must not resume at the old speed.
        self._sent_speeds = (0, 0)
        with self._lock:
            port, self._port = self._port, None
        if port is not None:
            try:
                port.close()
            except OSError:
                pass
