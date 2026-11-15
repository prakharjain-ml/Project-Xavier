"""Laptop <-> ESP32 bridge line protocol (docs/INTERFACES.md, "Laptop to ESP32 bridge"). Pure: no port here.

Laptop -> bridge, every 50 ms even when stopped:  "C,<seq>,<left>,<right>\\n"  or  "S,<seq>\\n"
Bridge -> laptop, every 50 ms:                    "D,<distance_cm>,<state>\\n"  (distance -1 = nothing in range)
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from shared.protocol import WHEEL_LIMIT, MotorCommand

BRIDGE_STATES = frozenset({"OK", "OBSTACLE", "WATCHDOG", "ESTOP"})
_STATUS = re.compile(r"D,(-?\d+),([A-Z_]+)")


@dataclass(frozen=True)
class BridgeStatus:
    distance_cm: int  # -1 = echo timeout / nothing in range (never 0)
    state: str  # OK | OBSTACLE | WATCHDOG | ESTOP


def clamp_speed(value: int) -> int:
    """Clamp again here even though control already clamps: defence in depth (rules/50-motors)."""
    return max(-WHEEL_LIMIT, min(WHEEL_LIMIT, int(value)))


def encode_command(command: MotorCommand, seq: int) -> str:
    """One protocol line. A stop flag or two zero speeds become an explicit S line."""
    left, right = clamp_speed(command.left), clamp_speed(command.right)
    if command.stop or (left == 0 and right == 0):
        return f"S,{seq}\n"
    return f"C,{seq},{left},{right}\n"


def parse_status(line: str) -> BridgeStatus | None:
    """Parse one bridge line; None for anything malformed (never guess from a broken line)."""
    match = _STATUS.fullmatch(line.strip())
    if match is None or match.group(2) not in BRIDGE_STATES:
        return None
    return BridgeStatus(int(match.group(1)), match.group(2))
