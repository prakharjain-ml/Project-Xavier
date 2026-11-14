"""The whole chain in one process (decision D3): flicker screen -> safety state machine -> motor driver -> ESP32.

Today the KEYBOARD stands in for the EEG decoder, so we can prove the wiring before the signal works:
  hold an arrow key = "the rider is looking at that arrow" (Intent with full confidence)
  no arrow, or two at once = NONE           SPACE = operator E-STOP           R = operator re-arm
Every real safety rule still applies: 1.5 s dwell before motion, stop on release, E-STOP latch, 20 Hz STOP
stream, ESP32 watchdog. Later the decoder replaces KeyboardIntentSource and sends the same Intent message.

HUMAN ONLY with a real port (wheels off the ground, kill switch in hand):
    python app.py --keyboard --serial /dev/cu.<ESP32 port>
Development (no hardware):
    python app.py --keyboard --mock
Threads: pygame on the main thread (macOS); control loop at CONTROL_HZ; motor driver at CONTROL_HZ.
"""

from __future__ import annotations

import argparse
import logging
import queue
import sys
import threading
import time

import pygame

from control.state_machine import ControlInputs, ControllerState, step
from interface.flicker import KEYS, offer_latest, open_display, run_flicker, show_warning
from interface.timing import FrameStats
from motors.driver import MotorDriver, open_serial
from motors.mock_serial import MockSerial
from shared.protocol import CONTROL_HZ, ControlStatus, Intent, State, StopRequest, StopSource, Target

log = logging.getLogger("app")

ARROW_TARGETS = {pygame.K_UP: Target.FWD, pygame.K_DOWN: Target.BACK,
                 pygame.K_LEFT: Target.LEFT, pygame.K_RIGHT: Target.RIGHT}
OPENBCI_DONGLE_MARK = "usbserial-DM"  # FTDI chip in the OpenBCI dongle; motor lines must never go there


def looks_like_openbci_dongle(port: str) -> bool:
    return OPENBCI_DONGLE_MARK in port


class KeyboardIntentSource:
    """Turns key events (main thread) into Intents and operator events (control thread). Thread-safe."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._held: frozenset[Target] = frozenset()
        self._stop_pressed = False
        self._rearm_pressed = False

    def on_event(self, event: pygame.event.Event) -> None:
        with self._lock:
            target = ARROW_TARGETS.get(event.key)
            if target is not None:
                self._held = self._held | {target} if event.type == pygame.KEYDOWN else self._held - {target}
            elif event.type == pygame.KEYDOWN and event.key == pygame.K_SPACE:
                self._stop_pressed = True
            elif event.type == pygame.KEYDOWN and event.key == pygame.K_r:
                self._rearm_pressed = True

    def snapshot(self, now: float) -> ControlInputs:
        """Inputs for one control tick. SPACE / R are one-shot: consumed here."""
        with self._lock:
            held, stop, rearm = self._held, self._stop_pressed, self._rearm_pressed
            self._stop_pressed = self._rearm_pressed = False
        # Exactly one arrow = that target; none or several = NONE (ambiguous input never moves the chair).
        target = next(iter(held)) if len(held) == 1 else Target.NONE
        intent = Intent(target=target, confidence=1.0 if target != Target.NONE else 0.0, t=now)
        stops = (StopRequest(StopSource.OPERATOR, now),) if stop else ()
        return ControlInputs(intent=intent, stop_requests=stops, rearm=rearm)


def control_tick(source: KeyboardIntentSource, driver, state: ControllerState,
                 now: float) -> tuple[ControllerState, ControlStatus]:
    """One 20 Hz tick: inputs -> state machine -> driver. Returns the new state and the status for the screen."""
    inputs = source.snapshot(now)
    inputs = ControlInputs(inputs.intent, inputs.stop_requests, inputs.rearm, driver.distance_cm())
    new_state, command, status = step(state, inputs, now)
    driver.send(command)
    if new_state.state != state.state:
        log.info("state %s -> %s (target %s, wheels %s)", state.state.value, new_state.state.value,
                 new_state.held_target.value, "STOP" if command.stop else f"{command.left},{command.right}")
    return new_state, status


def control_loop(source, driver, status_queue: queue.Queue, stop: threading.Event, result: dict) -> None:
    state, period = ControllerState(), 1.0 / CONTROL_HZ
    next_tick = time.monotonic()
    while not stop.is_set():
        state, status = control_tick(source, driver, state, time.monotonic())
        offer_latest(status_queue, status)
        result["state"] = state.state
        next_tick += period
        stop.wait(max(0.0, next_tick - time.monotonic()))  # fixed 20 Hz rate without drift


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="SSVEP chair: screen -> control -> motors")
    parser.add_argument("--keyboard", action="store_true", help="arrow keys stand in for the EEG decoder")
    port = parser.add_mutually_exclusive_group(required=True)
    port.add_argument("--mock", action="store_true", help="fake serial port (no hardware)")
    port.add_argument("--serial", metavar="PORT", help="ESP32 bridge port, e.g. /dev/cu.usbserial-0001 (HUMANS ONLY)")
    parser.add_argument("--seconds", type=float, default=None, help="quit after this many seconds")
    parser.add_argument("--windowed", action="store_true", help="development only")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None, start_events: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    args = parse_args(sys.argv[1:] if argv is None else argv)
    if not args.keyboard:
        log.error("the EEG decoder is not built yet: run with --keyboard")
        return 2
    if args.serial and looks_like_openbci_dongle(args.serial):
        log.error("%s looks like the OpenBCI dongle, not the ESP32. Refusing to send motor commands to it.",
                  args.serial)
        return 2
    mock = MockSerial() if args.mock else None
    driver = MotorDriver((lambda: mock) if mock else (lambda: open_serial(args.serial)))
    driver.start()  # streams STOP lines from now on, so the ESP32 never sees silence
    source, status_queue = KeyboardIntentSource(), queue.Queue(maxsize=1)
    stop, result, stats = threading.Event(), {"state": State.STOPPED}, FrameStats()
    pygame.init()
    try:
        screen, has_vsync = open_display(args.windowed)
        pygame.display.set_caption("SSVEP chair")
        clock = pygame.time.Clock()
        deadline = None if args.seconds is None else time.monotonic() + args.seconds
        for name in start_events or []:
            pygame.event.post(pygame.event.Event(pygame.KEYDOWN, key=KEYS[name]))
        if show_warning(screen, clock, deadline):
            threading.Thread(target=control_loop, args=(source, driver, status_queue, stop, result),
                             name="control", daemon=True).start()
            stats = run_flicker(screen, clock, None, has_vsync, deadline, status_queue, key_sink=source.on_event)
    finally:
        stop.set()
        driver.stop()  # final explicit STOP lines, then close the port
        pygame.quit()
    print(f"summary: frames={stats.frames} bridge_lines={driver.status().lines_sent} "
          f"final_state={result['state'].value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
