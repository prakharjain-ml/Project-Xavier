"""Laptop-side motor driver: the messenger between the safety state machine and the ESP32 bridge.

20 times a second it sends the newest MotorCommand down the USB cable as one protocol line, and reads back the
bridge's distance/state lines. Anything wrong (no fresh command, unplugged cable, no port) means it sends STOP
or nothing at all, and the ESP32's own 200 ms watchdog then stops the wheels.

It never chooses a port itself: the caller passes `open_port`. Auto-detecting is dangerous here because the
OpenBCI dongle also appears as /dev/cu.usbserial-*, and motor lines must never go to the EEG board.
Agents test this only with MockSerial; a human runs it with a real port (rules/50-motors.mdc).
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from motors.bridge_protocol import BridgeStatus, encode_command, parse_status
from shared.protocol import CONTROL_HZ, MotorCommand

log = logging.getLogger("motors.driver")

BAUD = 115200
COMMAND_STALE_S = 0.2  # no new command from control for this long -> send STOP (control runs every 50 ms)
BRIDGE_STALE_S = 0.5  # distance older than this is treated as unknown
REOPEN_S = 1.0  # retry opening a lost port this often
FINAL_STOP_LINES = 5  # stop lines sent when the driver shuts down


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
        try:
            port.write(encode_command(command, self._seq).encode())
        except OSError as error:
            log.error("bridge write failed (%s): port closed; ESP32 watchdog stops the wheels", error)
            self._close()
            return False
        with self._lock:
            self._seq += 1
            self._lines_sent += 1
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
        with self._lock:
            port, self._port = self._port, None
        if port is not None:
            try:
                port.close()
            except OSError:
                pass
