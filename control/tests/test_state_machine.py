"""One test per transition row of docs/SAFETY.md, plus fuzz and timing checks. Pure: the clock is passed in."""

import random

import pytest

from control.state_machine import ControlInputs, ControllerState, step
from shared.protocol import (
    CONF_THRESHOLD,
    CONTROL_HZ,
    DWELL_S,
    MAX_SPEED,
    OBSTACLE_STOP_CM,
    STALE_INTENT_S,
    TURN_SPEED,
    Intent,
    State,
    StopRequest,
    StopSource,
    Target,
)

NOW = 100.0
GOOD = CONF_THRESHOLD + 0.2
LOW = CONF_THRESHOLD - 0.05


def intent(target=Target.FWD, confidence=GOOD, t=NOW):
    return Intent(target=target, confidence=confidence, scores={}, t=t)


def in_state(state, held=Target.FWD, dwell_start=NOW - 0.5, last_stop_t=None):
    if state == State.STOPPED:
        return ControllerState(last_stop_t=last_stop_t)
    return ControllerState(state=state, held_target=held, dwell_start=dwell_start, last_stop_t=last_stop_t)


def run(prev, now=NOW, **inputs):
    return step(prev, ControlInputs(**inputs), now)


MOVING_STATES = [State.DWELLING, State.MOVING]
NON_ESTOP = [State.STOPPED, State.DWELLING, State.MOVING]


# --- Row: any | exception, unknown state, stale Intent -> STOPPED ---------------------------------------
@pytest.mark.parametrize("state", MOVING_STATES)
def test_stale_intent_stops(state):
    nxt, cmd, _ = run(in_state(state), intent=intent(t=NOW - STALE_INTENT_S - 0.01))
    assert nxt.state == State.STOPPED and cmd.stop


@pytest.mark.parametrize("state", MOVING_STATES)
def test_missing_intent_stops(state):
    nxt, cmd, _ = run(in_state(state), intent=None)
    assert nxt.state == State.STOPPED and cmd.stop


def test_exception_inside_transition_stops():
    broken = Intent(target=Target.FWD, confidence=None, scores={}, t=NOW)  # None >= 0.15 raises TypeError
    nxt, cmd, _ = run(in_state(State.MOVING), intent=broken)
    assert nxt.state == State.STOPPED and cmd.stop


def test_unknown_state_stops():
    nxt, cmd, _ = run(ControllerState(state="BOGUS"), intent=intent())
    assert nxt.state == State.STOPPED and cmd.stop


def test_exception_in_mapping_stops():
    def bad_mapping(_target):
        raise RuntimeError("mapping bug")

    nxt, cmd, _ = step(in_state(State.MOVING), ControlInputs(intent=intent()), NOW, mapping=bad_mapping)
    assert cmd.stop and nxt.state == State.STOPPED


# --- Row: any | StopRequest (ALPHA, OPERATOR, FAULT) -> E_STOP ------------------------------------------
@pytest.mark.parametrize("source", list(StopSource))
@pytest.mark.parametrize("state", NON_ESTOP)
def test_stop_request_latches_estop(state, source):
    nxt, cmd, _ = run(in_state(state), intent=intent(), stop_requests=(StopRequest(source, NOW),))
    assert nxt.state == State.E_STOP and cmd.stop


# --- Row: E_STOP | operator re-arm AND no active StopRequest -> STOPPED ---------------------------------
def test_rearm_clears_estop_when_stop_source_quiet():
    prev = in_state(State.E_STOP, last_stop_t=NOW - STALE_INTENT_S - 0.1)
    nxt, cmd, _ = run(prev, rearm=True, intent=intent())
    assert nxt.state == State.STOPPED and cmd.stop


def test_rearm_ignored_while_alpha_still_active():
    prev = in_state(State.E_STOP, last_stop_t=NOW - 0.1)
    assert run(prev, rearm=True).__getitem__(0).state == State.E_STOP


def test_rearm_ignored_when_a_new_stop_arrives_same_tick():
    prev = in_state(State.E_STOP, last_stop_t=NOW - 5)
    nxt, _, _ = run(prev, rearm=True, stop_requests=(StopRequest(StopSource.ALPHA, NOW),))
    assert nxt.state == State.E_STOP


def test_estop_stays_latched_without_rearm_even_with_good_or_stale_intent():
    prev = in_state(State.E_STOP, last_stop_t=NOW - 5)
    assert run(prev, intent=intent())[0].state == State.E_STOP
    assert run(prev, intent=intent(t=NOW - 10))[0].state == State.E_STOP  # stale must not un-latch


@pytest.mark.parametrize("state", NON_ESTOP)
def test_rearm_key_outside_estop_does_nothing_special(state):
    nxt, _, _ = run(in_state(state), rearm=True, intent=None)
    assert nxt.state == State.STOPPED


# --- Row: any non-E_STOP | target == FWD AND 0 < distance < OBSTACLE_STOP_CM -> STOPPED ----------------
@pytest.mark.parametrize("state", NON_ESTOP)
def test_forward_blocked_by_obstacle(state):
    nxt, cmd, _ = run(in_state(state), intent=intent(Target.FWD), distance_cm=OBSTACLE_STOP_CM - 20)
    assert nxt.state == State.STOPPED and cmd.stop


@pytest.mark.parametrize("target", [Target.LEFT, Target.RIGHT, Target.BACK])
def test_turns_and_reverse_allowed_near_obstacle(target):
    nxt, _, _ = run(in_state(State.STOPPED), intent=intent(target), distance_cm=OBSTACLE_STOP_CM - 20)
    assert nxt.state == State.DWELLING


@pytest.mark.parametrize("distance", [None, -1, 0, OBSTACLE_STOP_CM, 300])
def test_no_block_for_unknown_timeout_or_far_distance(distance):
    nxt, _, _ = run(in_state(State.STOPPED), intent=intent(Target.FWD), distance_cm=distance)
    assert nxt.state == State.DWELLING


# --- Row: STOPPED | valid target, confidence >= threshold, not blocked -> DWELLING ----------------------
def test_stopped_to_dwelling_on_confident_target():
    nxt, cmd, status = run(in_state(State.STOPPED), intent=intent(Target.LEFT))
    assert (nxt.state, nxt.held_target, nxt.dwell_start) == (State.DWELLING, Target.LEFT, NOW)
    assert cmd.stop and status.dwell_fraction == 0.0


@pytest.mark.parametrize("bad", [intent(Target.NONE), intent(confidence=LOW)])
def test_stopped_stays_stopped_without_confident_target(bad):
    assert run(in_state(State.STOPPED), intent=bad)[0].state == State.STOPPED


# --- Row: DWELLING | same target held for DWELL_S -> MOVING ---------------------------------------------
def test_dwelling_becomes_moving_after_dwell_time():
    prev = in_state(State.DWELLING, dwell_start=NOW - DWELL_S)
    nxt, cmd, status = run(prev, intent=intent())
    assert nxt.state == State.MOVING
    assert status.dwell_fraction == 1.0


def test_dwelling_keeps_dwelling_before_dwell_time():
    prev = in_state(State.DWELLING, dwell_start=NOW - DWELL_S + 0.05)
    nxt, cmd, status = run(prev, intent=intent())
    assert nxt.state == State.DWELLING and cmd.stop
    assert 0.9 < status.dwell_fraction < 1.0


# --- Row: DWELLING | target changes, NONE, or low confidence -> STOPPED ---------------------------------
@pytest.mark.parametrize("bad", [intent(Target.LEFT), intent(Target.NONE), intent(confidence=LOW)])
def test_dwelling_broken(bad):
    assert run(in_state(State.DWELLING), intent=bad)[0].state == State.STOPPED


# --- Row: MOVING | same target keeps winning -> MOVING (mapped command) ---------------------------------
@pytest.mark.parametrize("target, wheels", [
    (Target.FWD, (MAX_SPEED, MAX_SPEED)),
    (Target.BACK, (-(MAX_SPEED // 2), -(MAX_SPEED // 2))),
    (Target.LEFT, (-TURN_SPEED, TURN_SPEED)),
    (Target.RIGHT, (TURN_SPEED, -TURN_SPEED)),
])
def test_moving_emits_provisional_mapping(target, wheels):
    nxt, cmd, _ = run(in_state(State.MOVING, held=target), intent=intent(target))
    assert nxt.state == State.MOVING
    assert (cmd.left, cmd.right, cmd.stop) == (*wheels, False)


def test_mapping_output_is_clamped():
    nxt, cmd, _ = step(in_state(State.MOVING), ControlInputs(intent=intent()), NOW, mapping=lambda _t: (5000, -5000))
    assert (cmd.left, cmd.right) == (MAX_SPEED, -MAX_SPEED)


# --- Row: MOVING | target changes, NONE, or low confidence -> STOPPED -----------------------------------
@pytest.mark.parametrize("bad", [intent(Target.RIGHT), intent(Target.NONE), intent(confidence=LOW)])
def test_moving_broken(bad):
    nxt, cmd, _ = run(in_state(State.MOVING), intent=bad)
    assert nxt.state == State.STOPPED and cmd.stop


# --- Whole-system properties ----------------------------------------------------------------------------
def test_thousand_random_weak_intents_never_move():
    rng = random.Random(0)
    state, now = ControllerState(), NOW
    for _ in range(1000):
        now += 1 / CONTROL_HZ
        weak = Intent(target=rng.choice(list(Target)), confidence=rng.uniform(0, CONF_THRESHOLD - 1e-9), t=now)
        if rng.random() < 0.3:
            weak = Intent(target=Target.NONE, confidence=rng.uniform(0, 1), t=now)
        state, cmd, _ = step(state, ControlInputs(intent=weak, distance_cm=rng.choice([None, -1, 20, 200])), now)
        assert cmd.stop and state.state != State.MOVING


def test_twenty_hz_run_moves_only_after_dwell_and_stops_on_look_away():
    state, now, first_move = ControllerState(), NOW, None
    for tick in range(int(3 * CONTROL_HZ)):  # 3 s of looking at FWD
        now = NOW + tick / CONTROL_HZ
        state, cmd, _ = step(state, ControlInputs(intent=intent(t=now)), now)
        if not cmd.stop and first_move is None:
            first_move = now - NOW
    assert first_move == pytest.approx(DWELL_S)  # dwell clock starts on the tick the target first wins
    now += 1 / CONTROL_HZ
    state, cmd, _ = step(state, ControlInputs(intent=intent(Target.NONE, t=now)), now)
    assert state.state == State.STOPPED and cmd.stop  # look-away stops on the very next tick


def test_status_reports_fresh_confidence_and_distance():
    _, _, status = run(in_state(State.STOPPED), intent=intent(confidence=0.7), distance_cm=123)
    assert (status.confidence, status.distance_cm) == (0.7, 123)
    _, _, stale = run(in_state(State.STOPPED), intent=intent(t=NOW - 5))
    assert stale.confidence == 0.0 and stale.held_target == Target.NONE
