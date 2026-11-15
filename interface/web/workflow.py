"""Application workflow states for the web app, and which moves between them are legal.

These are SCREEN/SESSION states (what the rider is doing in the app). They are not the motor safety states
(STOPPED / DWELLING / MOVING / E_STOP in control/state_machine.py), which keep their own meaning.
"""

from __future__ import annotations

from enum import Enum


class Flow(str, Enum):
    IDLE = "IDLE"                        # welcome screen, no session
    DEVICE_SETUP = "DEVICE_SETUP"        # choose cameras / headset, start perception
    EYE_CALIBRATION = "EYE_CALIBRATION"  # browser shows dots, backend samples eye features
    EYE_VALIDATION = "EYE_VALIDATION"    # look at regions, count hits
    JAW_CALIBRATION = "JAW_CALIBRATION"  # relax / clench prompts (jaw confirm only)
    READY = "READY"                      # everything set; about to choose
    SELECTING = "SELECTING"              # look at objects, confirm one
    NAVIGATING = "NAVIGATING"            # destination confirmed, chair following the route
    PAUSED = "PAUSED"                    # emergency stop latched, or the controlling tab went quiet
    ARRIVED = "ARRIVED"                  # reached the destination (shown once)
    ERROR = "ERROR"                      # a subsystem failed; recovery action offered
    SESSION_ENDED = "SESSION_ENDED"


_ANY_ACTIVE = {Flow.DEVICE_SETUP, Flow.EYE_CALIBRATION, Flow.EYE_VALIDATION, Flow.JAW_CALIBRATION, Flow.READY,
               Flow.SELECTING, Flow.NAVIGATING, Flow.PAUSED, Flow.ARRIVED}

LEGAL: dict[Flow, set[Flow]] = {
    Flow.IDLE: {Flow.DEVICE_SETUP},
    Flow.DEVICE_SETUP: {Flow.EYE_CALIBRATION, Flow.JAW_CALIBRATION, Flow.READY},
    Flow.EYE_CALIBRATION: {Flow.EYE_VALIDATION, Flow.DEVICE_SETUP},
    Flow.EYE_VALIDATION: {Flow.JAW_CALIBRATION, Flow.READY, Flow.EYE_CALIBRATION, Flow.DEVICE_SETUP},
    Flow.JAW_CALIBRATION: {Flow.READY, Flow.DEVICE_SETUP, Flow.EYE_CALIBRATION},
    Flow.READY: {Flow.SELECTING, Flow.EYE_CALIBRATION, Flow.JAW_CALIBRATION, Flow.DEVICE_SETUP},
    Flow.SELECTING: {Flow.NAVIGATING, Flow.EYE_CALIBRATION, Flow.JAW_CALIBRATION, Flow.DEVICE_SETUP},
    Flow.NAVIGATING: {Flow.SELECTING, Flow.ARRIVED},
    Flow.PAUSED: {Flow.SELECTING},               # only through an explicit operator re-arm
    Flow.ARRIVED: {Flow.SELECTING},
    Flow.ERROR: {Flow.DEVICE_SETUP},
    Flow.SESSION_ENDED: {Flow.IDLE, Flow.DEVICE_SETUP},
}
# From any active state: an emergency stop / lost controller pauses, a failure errors, and the session can end.
for _state in _ANY_ACTIVE:
    LEGAL[_state] |= {Flow.PAUSED, Flow.ERROR, Flow.SESSION_ENDED}
LEGAL[Flow.ERROR] |= {Flow.SESSION_ENDED}
LEGAL[Flow.PAUSED].discard(Flow.PAUSED)

# States in which the chair may be driven at all (anything else sends STOP every tick).
DRIVABLE = {Flow.SELECTING, Flow.NAVIGATING}
# States that need fresh perception (camera, gaze) running.
LIVE_VIEW = {Flow.READY, Flow.SELECTING, Flow.NAVIGATING, Flow.PAUSED, Flow.ARRIVED}


class IllegalTransition(ValueError):
    pass


def check(current: Flow, target: Flow) -> Flow:
    """Return target if current -> target is legal, else raise IllegalTransition (the caller refuses the action)."""
    if target == current or target in LEGAL[current]:
        return target
    raise IllegalTransition(f"{current.value} -> {target.value} is not allowed")
