"""The whole chain in one process (decision D3): flicker screen -> safety state machine -> motor driver -> ESP32.

Intent sources (the EEG decoder will be a third one, sending the same Intent message):
--keyboard: the KEYBOARD stands in for the decoder, so we can prove the wiring before the signal works:
  hold an arrow key = "the rider is looking at that arrow" (Intent with full confidence)
  no arrow, or two at once = NONE           SPACE = operator E-STOP           R = operator re-arm
--gaze: webcam eye tracking (vision/gaze*.py) picks the arrow you look at; arrows are drawn static.
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
import os
import queue
import subprocess
import sys
import threading
import time

import pygame

from control.state_machine import ControlInputs, ControllerState, step
from interface.flicker import KEYS, offer_latest, open_display, run_flicker, show_warning
from interface.timing import FrameStats
from motors.driver import MotorDriver, looks_like_openbci_dongle, open_serial
from motors.mock_serial import MockSerial
from shared.latest import drain_newest
from shared.protocol import (
    CONTROL_HZ,
    STALE_INTENT_S,
    ControlStatus,
    Intent,
    State,
    StopRequest,
    StopSource,
    Target,
)
from vision.gaze import ARROW_REGIONS, pick_region  # numpy only: no cv2 here
from vision.gaze_link import calibration_hint, calibration_ready, gaze_backend, start_gaze_tracker
from vision.gaze_tracker import CALIBRATION_PATH  # module top imports no cv2/mediapipe

log = logging.getLogger("app")

ARROW_TARGETS = {pygame.K_UP: Target.FWD, pygame.K_DOWN: Target.BACK,
                 pygame.K_LEFT: Target.LEFT, pygame.K_RIGHT: Target.RIGHT}
class OperatorKeys:
    """Teammate keys in every input mode: SPACE = operator E-STOP, R = re-arm. One-shot presses, thread-safe
    (key events arrive on the main thread, the control thread consumes them)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._stop = self._rearm = False

    def handle(self, event: pygame.event.Event) -> bool:
        """Record SPACE / R. Returns True if the event was an operator key."""
        if event.type != pygame.KEYDOWN or event.key not in (pygame.K_SPACE, pygame.K_r):
            return False
        with self._lock:
            if event.key == pygame.K_SPACE:
                self._stop = True
            else:
                self._rearm = True
        return True

    def take(self, now: float) -> tuple[tuple[StopRequest, ...], bool]:
        """(stop requests, re-arm) pressed since the last tick, then cleared."""
        with self._lock:
            stop, rearm = self._stop, self._rearm
            self._stop = self._rearm = False
        return ((StopRequest(StopSource.OPERATOR, now),) if stop else ()), rearm


class KeyboardIntentSource:
    """Turns key events (main thread) into Intents and operator events (control thread). Thread-safe."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._held: frozenset[Target] = frozenset()
        self._operator = OperatorKeys()

    def on_event(self, event: pygame.event.Event) -> None:
        if self._operator.handle(event):
            return
        target = ARROW_TARGETS.get(event.key)
        if target is not None:
            with self._lock:
                self._held = self._held | {target} if event.type == pygame.KEYDOWN else self._held - {target}

    def snapshot(self, now: float) -> ControlInputs:
        """Inputs for one control tick. SPACE / R are one-shot: consumed here."""
        with self._lock:
            held = self._held
        stops, rearm = self._operator.take(now)
        # Exactly one arrow = that target; none or several = NONE (ambiguous input never moves the chair).
        target = next(iter(held)) if len(held) == 1 else Target.NONE
        intent = Intent(target=target, confidence=1.0 if target != Target.NONE else 0.0, t=now)
        return ControlInputs(intent=intent, stop_requests=stops, rearm=rearm)


class GazeIntentSource:
    """Gaze samples from the tracker process -> Intents. The keyboard only gives operator keys (SPACE, R).

    Looking at the top/left/right/bottom arrow region = that target. No face, eyes closed longer than a blink,
    gaze in the centre or between regions, or a sample older than STALE_INTENT_S = NONE, so the chair stops.
    """

    def __init__(self, gaze_queue) -> None:
        self._queue = gaze_queue
        self._lock = threading.Lock()
        self._sample = None  # newest GazeSample (only touched by the control thread)
        self._region: str | None = None  # current region, kept for hysteresis
        self._operator = OperatorKeys()
        self._recentre_pressed = False
        self._offset = (0.0, 0.0)  # added to every gaze point; set by re-centring (C key)
        self._cursor: tuple[float, float] | None = None  # for the on-screen gaze dot

    def on_event(self, event: pygame.event.Event) -> None:
        if self._operator.handle(event):
            return
        if event.type == pygame.KEYDOWN and event.key == pygame.K_c:
            with self._lock:
                self._recentre_pressed = True  # rider is looking at the centre "+" right now

    def cursor(self) -> tuple[float, float] | None:
        """Corrected gaze point for the on-screen dot (main thread reads it)."""
        with self._lock:
            return self._cursor

    def snapshot(self, now: float) -> ControlInputs:
        self._sample = sample = drain_newest(self._queue, self._sample)  # only the newest gaze sample matters
        stops, rearm = self._operator.take(now)
        with self._lock:
            recentre, self._recentre_pressed = self._recentre_pressed, False
        fresh = sample is not None and sample.point is not None and now - sample.t <= STALE_INTENT_S
        if fresh and recentre:
            # Drift correction: whatever we read while the rider looks at the centre becomes (0.5, 0.5).
            self._offset = (0.5 - sample.point[0], 0.5 - sample.point[1])
        point = (min(1.0, max(0.0, sample.point[0] + self._offset[0])),
                 min(1.0, max(0.0, sample.point[1] + self._offset[1]))) if fresh else None
        with self._lock:
            self._cursor = point
        self._region = pick_region(point, ARROW_REGIONS, self._region) if point else None
        target = Target(self._region) if self._region else Target.NONE
        intent = Intent(target=target, confidence=1.0 if target != Target.NONE else 0.0, t=now)
        return ControlInputs(intent=intent, stop_requests=stops, rearm=rearm)


def start_gaze_process(eye_camera: int, calibration: str):
    """Start the eye tracker program; see vision/gaze_link.py. Kept here so callers and tests use one name."""
    return start_gaze_tracker(eye_camera, calibration)


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
    intent = parser.add_mutually_exclusive_group(required=True)
    intent.add_argument("--keyboard", action="store_true", help="arrow keys stand in for the EEG decoder")
    intent.add_argument("--gaze", action="store_true", help="webcam eye tracking chooses the arrow")
    parser.add_argument("--eye-camera", default="auto", help="camera that sees the rider's face, or auto (--gaze)")
    parser.add_argument("--calibration", default=CALIBRATION_PATH, help="gaze calibration file (--gaze)")
    port = parser.add_mutually_exclusive_group(required=True)
    port.add_argument("--mock", action="store_true", help="fake serial port (no hardware)")
    port.add_argument("--serial", metavar="PORT", help="ESP32 bridge port, e.g. /dev/cu.usbserial-0001 (HUMANS ONLY)")
    parser.add_argument("--seconds", type=float, default=None, help="quit after this many seconds")
    parser.add_argument("--windowed", action="store_true", help="development only")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None, start_events: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    args = parse_args(sys.argv[1:] if argv is None else argv)
    if args.serial and looks_like_openbci_dongle(args.serial):
        log.error("%s looks like the OpenBCI dongle, not the ESP32. Refusing to send motor commands to it.",
                  args.serial)
        return 2
    if args.gaze and not calibration_ready(gaze_backend(), args.calibration):
        log.error("no gaze calibration for the %s tracker: run `%s` first", gaze_backend(),
                  calibration_hint(gaze_backend()))
        return 2
    mock = MockSerial() if args.mock else None
    driver = MotorDriver((lambda: mock) if mock else (lambda: open_serial(args.serial)))
    driver.start()  # streams STOP lines from now on, so the ESP32 never sees silence
    gaze_process = gaze_stop = None
    if args.gaze:  # start early: the camera and face model take a moment to warm up
        gaze_process, gaze_queue, gaze_stop = start_gaze_process(args.eye_camera, args.calibration)
        source = GazeIntentSource(gaze_queue)
    else:
        source = KeyboardIntentSource()
    status_queue = queue.Queue(maxsize=1)
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
            stats = run_flicker(screen, clock, None, has_vsync, deadline, status_queue, key_sink=source.on_event,
                                static=args.gaze,  # gaze mode: arrows do not flicker
                                cursor=source.cursor if args.gaze else None)
    finally:
        stop.set()
        driver.stop()  # final explicit STOP lines, then close the port
        if gaze_stop is not None:
            gaze_stop.set()
        if gaze_process is not None:
            gaze_process.terminate()  # the tracker also exits by itself if this app dies
            try:
                gaze_process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                gaze_process.kill()
        pygame.quit()
    print(f"summary: frames={stats.frames} bridge_lines={driver.status().lines_sent} "
          f"final_state={result['state'].value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
