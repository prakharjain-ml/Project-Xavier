"""Drive the hoverboard through Keshav's chair_control library (firmware/chair_control/chair.py).

Same interface as motors/driver.MotorDriver (start, send, distance_cm, stop), so the drive screen can use either.
Every wheel command from the route follower is turned into one of Keshav's functions and logged in words:
equal speeds -> chair.forward / chair.backward, opposite speeds -> chair.turn_left / chair.turn_right,
anything else -> chair.drive(left, right) (a curve), zero -> chair.stop().

Safety added on top of the library: chair.py keeps sending the LAST speed until told otherwise, so if the drive
screen froze the wheels would keep turning. A watchdog here calls chair.stop() when no fresh command has arrived for
COMMAND_STALE_S (the ESP32's own 200 ms watchdog only helps when the laptop stops sending altogether).
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable

from shared.protocol import MotorCommand

log = logging.getLogger("motors.chair_driver")

COMMAND_STALE_S = 0.2  # no new command for this long -> stop (the screen sends one every pass, many per second)
WATCH_PERIOD_S = 0.05
SPEED_CAP = 700  # chair.py's own cap for this program (its default is 850): turns spin at 700, straight at 450
LOG_CHANGE = 15  # log again when either wheel changes by more than this (avoids a line per pass)


def describe(left: int, right: int) -> str:
    """The chair.py function a wheel pair corresponds to, as text (also used for the log)."""
    if left == 0 and right == 0:
        return "chair.stop()"
    if left == right:
        return f"chair.forward({left})" if left > 0 else f"chair.backward({-left})"
    if left == -right:
        return f"chair.turn_right({left})" if left > 0 else f"chair.turn_left({right})"
    side = "right" if left > right else "left"
    return f"chair.drive({left}, {right})  # curve {side}"


class ChairDriver:
    def __init__(self, port: str, chair_factory: Callable | None = None, stale_s: float = COMMAND_STALE_S) -> None:
        self._port, self._factory, self._stale_s = port, chair_factory, stale_s
        self._chair = None
        self._lock = threading.Lock()
        self._last = (0, 0)
        self._last_t = 0.0
        self._logged: tuple[int, int] | None = None
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._watch, name="chair-watchdog", daemon=True)

    def start(self) -> None:
        if self._factory is None:
            from firmware.chair_control import Chair  # imported here so tests never need pyserial or a port

            self._factory = lambda port: Chair(port, max_speed=SPEED_CAP)
        self._chair = self._factory(self._port)  # opens the port; waits ~2 s for the ESP32 to find both boards
        log.info("chair_control connected on %s (bridge state %s)", self._port, getattr(self._chair, "state", "?"))
        self._thread.start()

    def send(self, command: MotorCommand) -> None:
        left, right = (0, 0) if command.stop else (int(command.left), int(command.right))
        with self._lock:
            self._last, self._last_t = (left, right), time.monotonic()
            self._apply(left, right)

    def distance_cm(self) -> int | None:
        chair = self._chair
        if chair is None or getattr(chair, "state", "?") == "?":
            return None
        return int(chair.distance_cm)

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread.is_alive():
            self._thread.join(timeout=1.0)
        if self._chair is not None:
            self._chair.close()  # sends stop several times and frees the port
            log.info("chair_control closed: wheels stopped")

    def _apply(self, left: int, right: int) -> None:
        chair = self._chair
        if chair is None:
            return
        if left == 0 and right == 0:
            chair.stop()
        elif left == right and left > 0:
            chair.forward(left)
        elif left == right:
            chair.backward(-left)
        elif left == -right and left > 0:
            chair.turn_right(left)
        elif left == -right:
            chair.turn_left(right)
        else:
            chair.drive(left, right)
        logged = self._logged
        if logged is None or max(abs(left - logged[0]), abs(right - logged[1])) > LOG_CHANGE or \
                ((left, right) == (0, 0)) != (logged == (0, 0)):
            self._logged = (left, right)
            log.info("MOTOR %s", describe(left, right))

    def _watch(self) -> None:
        while not self._stop_event.wait(WATCH_PERIOD_S):
            with self._lock:
                stale = time.monotonic() - self._last_t > self._stale_s
                if stale and self._last != (0, 0):
                    log.warning("no fresh drive command for %.1f s: chair.stop()", self._stale_s)
                    self._last = (0, 0)
                    self._apply(0, 0)
