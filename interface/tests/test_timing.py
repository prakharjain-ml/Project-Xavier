"""Frame-counted flicker math. No display needed."""

import pytest

from interface.timing import FrameStats, flicker_schedule, is_on, update_frame_stats
from shared.protocol import DISPLAY_HZ, TARGET_FREQS_HZ, Target

FRAME_S = 1 / DISPLAY_HZ


def test_is_on_follows_the_on_off_split():
    # 9-frame cycle (6.67 Hz) = 5 bright then 4 dark, repeating.
    pattern = [is_on(i, 9) for i in range(18)]
    assert pattern == [True] * 5 + [False] * 4 + [True] * 5 + [False] * 4


@pytest.mark.parametrize("target", list(TARGET_FREQS_HZ))
def test_one_second_of_frames_gives_the_exact_frequency(target):
    frames = flicker_schedule()[target]
    pattern = [is_on(i, frames) for i in range(DISPLAY_HZ * 3)]
    rising_edges = sum(1 for a, b in zip(pattern, pattern[1:]) if b and not a) + int(pattern[0])
    assert rising_edges / 3 == pytest.approx(TARGET_FREQS_HZ[target], abs=0.34)  # 3 s, whole cycles only


def test_schedule_is_9_7_5_4_frames():
    assert flicker_schedule() == {Target.FWD: 9, Target.LEFT: 7, Target.RIGHT: 5, Target.BACK: 4}


def test_frame_stats_counts_drops_and_slow_frames():
    stats = FrameStats()
    for dt in (FRAME_S, FRAME_S, 0.025, 3 * FRAME_S):  # one 25 ms frame, one triple-length gap
        stats = update_frame_stats(stats, dt)
    assert stats.frames == 4
    assert stats.slow_frames == 2  # both > 20 ms
    assert stats.dropped == 1 + 2  # 25 ms ~ 1.5 frames -> 1 dropped; 50 ms = 3 frames -> 2 dropped
    assert stats.max_frame_s == pytest.approx(3 * FRAME_S)


def test_frame_stats_is_immutable():
    stats = FrameStats()
    update_frame_stats(stats, FRAME_S)
    assert stats.frames == 0
