"""Safety state machine (docs/SAFETY.md). Decides, 20 times a second, what the wheels may do.

It is a pure function: step(previous_state, inputs, now) -> (next_state, MotorCommand, ControlStatus).
No threads, no clock reads, no I/O, so every rule can be tested exactly. The caller (app.py) runs it at
CONTROL_HZ and passes time.monotonic().

STOP is the default: any exception, unknown state, missing or stale data produces a stop command.

Two readings of SAFETY.md made explicit here (logged in PROGRESS.md for the team):
1. "any | stale Intent -> STOPPED" does not apply in E_STOP: a stale signal must never clear a latched stop
   (only the operator re-arm can).
2. "no active StopRequest" = no StopRequest in the last STOP_ACTIVE_S seconds. The alpha detector is expected
   to keep sending StopRequest while the eyes stay closed.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Callable
from dataclasses import dataclass, field, replace

from shared.protocol import (
    CONF_THRESHOLD,
    DWELL_S,
    MAX_SPEED,
    OBSTACLE_STOP_CM,
    STALE_INTENT_S,
    TURN_SPEED,
    ControlStatus,
    Intent,
    MotorCommand,
    State,
    StopRequest,
    Target,
)

log = logging.getLogger("control.state_machine")

STOP_ACTIVE_S = STALE_INTENT_S  # a stop source counts as still active if it spoke this recently

Mapping = Callable[[Target], tuple[int, int]]


@dataclass(frozen=True)
class ControllerState:
    state: State = State.STOPPED
    held_target: Target = Target.NONE  # target being dwelled on or moved toward
    dwell_start: float | None = None  # monotonic time DWELLING began
    last_stop_t: float | None = None  # newest StopRequest time from any source (for the re-arm rule)


@dataclass(frozen=True)
class ControlInputs:
    intent: Intent | None = None  # newest decoder answer, or None if none has arrived
    stop_requests: tuple[StopRequest, ...] = field(default_factory=tuple)  # arrived since the last tick
    rearm: bool = False  # operator pressed the re-arm key this tick
    distance_cm: int | None = None  # newest ultrasonic distance; None or -1 = unknown / clear


def provisional_mapping(target: Target) -> tuple[int, int]:
    """Target -> (left, right) wheel speeds, from INTERFACES.md. Pratosh's control/mapping.py replaces this.

    Positive = wheel rolls the chair forward; VERIFY wheel signs on the bench (QUESTIONS.md #5).
    """
    return {
        Target.FWD: (MAX_SPEED, MAX_SPEED),
        Target.BACK: (-(MAX_SPEED // 2), -(MAX_SPEED // 2)),  # reverse slower: the rider cannot see behind
        Target.LEFT: (-TURN_SPEED, TURN_SPEED),  # turn in place
        Target.RIGHT: (TURN_SPEED, -TURN_SPEED),
    }.get(target, (0, 0))


def forward_blocked(distance_cm: int | None) -> bool:
    """A valid reading (> 0) closer than OBSTACLE_STOP_CM. -1 means echo timeout = nothing in range."""
    return distance_cm is not None and 0 < distance_cm < OBSTACLE_STOP_CM


def step(prev: ControllerState, inputs: ControlInputs, now: float,
         mapping: Mapping = provisional_mapping) -> tuple[ControllerState, MotorCommand, ControlStatus]:
    """One control tick. Never raises: any error -> STOPPED (or stay E_STOP) and a stop command."""
    try:
        nxt = _transition(prev, inputs, now)
    except Exception:
        log.exception("state machine error -> STOP")
        nxt = _fallback(prev)
    try:
        command = _command(nxt, inputs, now, mapping)
    except Exception:
        log.exception("mapping error -> STOP")
        nxt, command = _fallback(prev), MotorCommand.halt(now)
    return nxt, command, _status(nxt, inputs, now)


def _fallback(prev: ControllerState) -> ControllerState:
    latched = isinstance(prev.state, State) and prev.state == State.E_STOP
    return ControllerState(state=State.E_STOP if latched else State.STOPPED, last_stop_t=prev.last_stop_t)


def _transition(prev: ControllerState, inputs: ControlInputs, now: float) -> ControllerState:
    stop_times = [r.t for r in inputs.stop_requests]
    last_stop_t = max([prev.last_stop_t] + stop_times if prev.last_stop_t is not None else stop_times,
                      default=None)
    stopped = ControllerState(last_stop_t=last_stop_t)

    # Row: any | StopRequest -> E_STOP (latched).
    if stop_times:
        return ControllerState(state=State.E_STOP, last_stop_t=last_stop_t)

    # Row: E_STOP | re-arm AND no active StopRequest -> STOPPED. Nothing else leaves E_STOP.
    if prev.state == State.E_STOP:
        stop_active = last_stop_t is not None and now - last_stop_t <= STOP_ACTIVE_S
        return stopped if inputs.rearm and not stop_active else replace(prev, last_stop_t=last_stop_t)

    # Row: any | unknown state, stale or missing Intent -> STOPPED.
    if not isinstance(prev.state, State):
        log.error("unknown state %r -> STOPPED", prev.state)
        return stopped
    intent = inputs.intent
    if intent is None or now - intent.t > STALE_INTENT_S:
        return stopped

    confident = intent.target != Target.NONE and intent.confidence >= CONF_THRESHOLD
    # Row: any non-E_STOP | FWD while an obstacle is close -> STOPPED (non-latching; turns stay allowed).
    if not confident or (intent.target == Target.FWD and forward_blocked(inputs.distance_cm)):
        return stopped

    if prev.state == State.STOPPED:  # Row: STOPPED -> DWELLING, dwell timer starts now
        return ControllerState(State.DWELLING, intent.target, now, last_stop_t)
    if intent.target != prev.held_target:  # Rows: DWELLING/MOVING | target changes -> STOPPED
        return stopped
    if prev.state == State.DWELLING:  # Row: DWELLING | held for DWELL_S -> MOVING
        held_long_enough = now - prev.dwell_start >= DWELL_S - 1e-9  # tolerance for float tick sums
        return replace(prev, state=State.MOVING if held_long_enough else State.DWELLING, last_stop_t=last_stop_t)
    return replace(prev, last_stop_t=last_stop_t)  # Row: MOVING | same target keeps winning -> MOVING


def _clamp(value: int) -> int:
    return max(-MAX_SPEED, min(MAX_SPEED, int(value)))


def _command(state: ControllerState, inputs: ControlInputs, now: float, mapping: Mapping) -> MotorCommand:
    if state.state != State.MOVING:
        return MotorCommand.halt(now)
    if state.held_target == Target.FWD and forward_blocked(inputs.distance_cm):  # defence in depth
        return MotorCommand.halt(now)
    left, right = mapping(state.held_target)
    return MotorCommand(_clamp(left), _clamp(right), False, now)


def _status(state: ControllerState, inputs: ControlInputs, now: float) -> ControlStatus:
    intent = inputs.intent
    fresh = intent is not None and now - intent.t <= STALE_INTENT_S
    if state.state == State.DWELLING and state.dwell_start is not None:
        fraction = min(1.0, max(0.0, (now - state.dwell_start) / DWELL_S))
    else:
        fraction = 1.0 if state.state == State.MOVING else 0.0
    confidence = intent.confidence if fresh and isinstance(intent.confidence, (int, float)) else 0.0
    return ControlStatus(
        state=state.state if isinstance(state.state, State) else State.STOPPED,
        held_target=state.held_target if state.state in (State.DWELLING, State.MOVING) else Target.NONE,
        dwell_fraction=fraction,
        confidence=0.0 if math.isnan(confidence) else float(confidence),
        scores=dict(intent.scores) if fresh else {},
        distance_cm=inputs.distance_cm,
    )
