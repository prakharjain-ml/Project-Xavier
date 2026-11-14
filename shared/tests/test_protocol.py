"""shared/protocol.py must match docs/INTERFACES.md exactly. The doc is parsed, not retyped, so a change to
either side without the other fails here."""

import re
from itertools import combinations
from pathlib import Path

import pytest

from shared import protocol
from shared.protocol import Target, frames_per_cycle, on_off_split

DOC = Path(__file__).resolve().parents[2] / "docs" / "INTERFACES.md"
NUMBER = r"\d+(?:\.\d+)?"


def _number(text: str) -> float:
    """'60', '0.15' or '60/9' -> float. Anything else is a doc format we do not understand: fail loudly."""
    text = text.strip()
    match = re.fullmatch(rf"({NUMBER})(?:/({NUMBER}))?", text)
    if not match:
        raise ValueError(f"cannot read number {text!r} from INTERFACES.md")
    value = float(match.group(1))
    return value / float(match.group(2)) if match.group(2) else value


def _value(text: str):
    text = text.strip()
    if text.startswith("{"):  # {FWD: 60/9, LEFT: 60/7, ...}
        pairs = re.findall(r"(\w+):\s*([^,}]+)", text)
        return {key: _number(val) for key, val in pairs}
    if text.startswith("("):  # (5, 40)
        return tuple(_number(part) for part in text.strip("()").split(","))
    return _number(text)


def doc_constants() -> dict:
    """Read the '## Constants' table of INTERFACES.md into {name: value}."""
    section = DOC.read_text().split("## Constants", 1)[1].split("\n## ", 1)[0]
    constants = {}
    for row in section.splitlines():
        cells = [c.strip() for c in row.strip().strip("|").split("|")]
        names = re.findall(r"`(\w+)`", cells[0]) if len(cells) >= 2 else []
        if not names:
            continue  # header or separator row
        values = cells[1].split(" / ") if len(names) > 1 else [cells[1]]
        constants.update(zip(names, (_value(v) for v in values)))
    return constants


def test_doc_table_was_read():
    assert len(doc_constants()) >= 13  # guards against the parser silently reading nothing


@pytest.mark.parametrize("name", [n for n in doc_constants() if n != "TARGET_FREQS_HZ"])
def test_constant_matches_doc(name):
    expected = doc_constants()[name]
    actual = getattr(protocol, name)
    if isinstance(expected, tuple):
        assert tuple(actual) == pytest.approx(expected)
    else:
        assert actual == pytest.approx(expected)


def test_target_frequencies_match_doc():
    expected = doc_constants()["TARGET_FREQS_HZ"]
    assert {t.value: f for t, f in protocol.TARGET_FREQS_HZ.items()} == pytest.approx(expected)


def test_every_frequency_is_exact_on_the_display():
    frames = [frames_per_cycle(f) for f in protocol.TARGET_FREQS_HZ.values()]
    assert frames == [9, 7, 5, 4]


def test_no_target_is_a_harmonic_of_another():
    # The brain also answers at 2f; if one target were double another, looking at one would light up both.
    for a, b in combinations(protocol.TARGET_FREQS_HZ.values(), 2):
        low, high = sorted((a, b))
        assert abs(high - 2 * low) > 0.5


def test_band_pass_keeps_every_second_harmonic():
    assert 2 * max(protocol.TARGET_FREQS_HZ.values()) < protocol.BANDPASS_HZ[1]


def test_on_off_split_matches_interface_rules():
    assert [on_off_split(n) for n in (9, 7, 5, 4)] == [(5, 4), (4, 3), (3, 2), (2, 2)]


def test_frames_per_cycle_rejects_inexact_rates():
    with pytest.raises(ValueError, match="not 60/n"):
        frames_per_cycle(11.0)
    with pytest.raises(ValueError):
        frames_per_cycle(30.0001)


def test_messages_are_immutable():
    command = protocol.MotorCommand.halt(1.0)
    assert (command.left, command.right, command.stop) == (0, 0, True)
    with pytest.raises(Exception):
        command.left = 5  # frozen dataclass


def test_target_enum_has_none():
    assert Target.NONE.value == "NONE"
