"""Shared contracts: every message, enum and constant passed between folders.

Generated from docs/INTERFACES.md (the source of truth). To change a value: edit INTERFACES.md first, then this
file; shared/tests/test_protocol.py fails if the two disagree. Never redefine these in another folder.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

PROTOCOL_VERSION = 1  # put in every JSON message between processes; bump on any breaking change

# ---------------------------------------------------------------- enums


class Target(str, Enum):
    FWD = "FWD"
    LEFT = "LEFT"
    RIGHT = "RIGHT"
    BACK = "BACK"
    NONE = "NONE"  # a real decoder answer: no target is winning


class State(str, Enum):
    STOPPED = "STOPPED"
    DWELLING = "DWELLING"
    MOVING = "MOVING"
    E_STOP = "E_STOP"


class StopSource(str, Enum):
    """Latching stop sources (E_STOP). Obstacle distance is NOT here: it blocks forward motion without latching."""

    ALPHA = "ALPHA"
    OPERATOR = "OPERATOR"
    FAULT = "FAULT"


# ---------------------------------------------------------------- constants (docs/INTERFACES.md, "Constants")

DISPLAY_HZ = 60
TARGET_FREQS_HZ: dict[Target, float] = {
    Target.FWD: 60 / 9,  # 6.67 Hz, 9 frames per cycle
    Target.LEFT: 60 / 7,  # 8.57 Hz, 7 frames
    Target.RIGHT: 12.0,  # 5 frames
    Target.BACK: 15.0,  # 4 frames
}
WINDOW_S = 1.5
STEP_S = 0.25
CONF_THRESHOLD = 0.15
DWELL_S = 1.5
STALE_INTENT_S = 0.5
CONTROL_HZ = 20
BRIDGE_WATCHDOG_MS = 200
BANDPASS_HZ = (5, 40)
ALPHA_BAND_HZ = (8, 13)
MAX_SPEED = 350   # forward / backward wheel speed (450 felt too fast in the live test, Sun Nov 15)
TURN_SPEED = 700  # spin in place: one wheel back, one forward, both at this speed
WHEEL_LIMIT = max(MAX_SPEED, TURN_SPEED)  # per-wheel safety clamp (chair.py caps again, bridge.ino at 910)
OBSTACLE_STOP_CM = 50

# ---------------------------------------------------------------- flicker math (shared by interface/ and vision/)


def frames_per_cycle(freq_hz: float, display_hz: int = DISPLAY_HZ) -> int:
    """Whole number of display frames in one flicker cycle. Rejects rates the screen cannot show exactly."""
    frames = display_hz / freq_hz
    whole = round(frames)
    if whole < 2 or abs(frames - whole) > 1e-6:
        raise ValueError(
            f"{freq_hz:.3f} Hz is not {display_hz}/n for a whole n >= 2 (got {frames:.3f} frames); "
            f"the flicker would be uneven and smear the EEG peak"
        )
    return whole


def on_off_split(frames: int) -> tuple[int, int]:
    """Frames bright vs dark per cycle, as even as possible: 9 -> (5, 4), 7 -> (4, 3), 5 -> (3, 2), 4 -> (2, 2)."""
    on = (frames + 1) // 2
    return on, frames - on


# ---------------------------------------------------------------- messages (frozen: never edited after creation)


@dataclass(frozen=True)
class Intent:
    """bci -> control, interface. The decoder's latest answer."""

    target: Target
    confidence: float  # 0-1, margin-based
    scores: dict[Target, float] = field(default_factory=dict)
    t: float = 0.0  # time.monotonic() at window end


@dataclass(frozen=True)
class StopRequest:
    """bci/alpha or operator key -> control. Puts control into latched E_STOP."""

    source: StopSource
    t: float


@dataclass(frozen=True)
class MotorCommand:
    """control -> motors. stop=True means both wheels zero, whatever left/right say."""

    left: int
    right: int
    stop: bool
    t: float

    @staticmethod
    def halt(t: float) -> "MotorCommand":
        return MotorCommand(0, 0, True, t)


@dataclass(frozen=True)
class ControlStatus:
    """control -> interface, for the dwell bars and debug overlay."""

    state: State
    held_target: Target
    dwell_fraction: float  # 0-1
    confidence: float = 0.0  # 0.0 if stale
    scores: dict[Target, float] = field(default_factory=dict)
    distance_cm: int | None = None


@dataclass(frozen=True)
class TargetInfo:
    """One Mode 2 camera target."""

    id: int  # stable track id
    label: str
    bbox: tuple[float, float, float, float]  # x1, y1, x2, y2 px
    freq_hz: float


@dataclass(frozen=True)
class TargetSet:
    """vision -> interface, control (Mode 2). Up to 4 targets."""

    targets: tuple[TargetInfo, ...]
    t: float


@dataclass(frozen=True)
class GoalHint:
    """vision -> control (Mode 2). Where the chosen target is; control alone turns this into wheel speeds."""

    target_id: int  # negative = Gemini-only target (e.g. a door)
    offset: float  # -1 far left, 0 straight ahead, +1 far right
    distance_m: float | None  # box-size estimate, never a safety signal
    t: float
