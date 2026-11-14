"""Frame-counted flicker timing (pure, no pygame).

The screen redraws exactly DISPLAY_HZ times a second. A target at f Hz repeats every DISPLAY_HZ / f frames,
so we decide bright/dark from the frame number, never from a clock: clocks drift and jitter, which smears the
EEG peak; the frame count is locked to the display itself.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from shared.protocol import DISPLAY_HZ, TARGET_FREQS_HZ, Target, frames_per_cycle, on_off_split

SLOW_FRAME_S = 0.020  # log any frame longer than this (rules: "log any frame over 20 ms")


def flicker_schedule(display_hz: int = DISPLAY_HZ) -> dict[Target, int]:
    """Frames per cycle for each target. Raises ValueError if a frequency is not exact on this display."""
    return {target: frames_per_cycle(freq, display_hz) for target, freq in TARGET_FREQS_HZ.items()}


def is_on(frame_index: int, frames: int) -> bool:
    """Bright for the first `on` frames of each cycle, dark for the rest (9 frames -> 5 on, 4 off)."""
    on, _off = on_off_split(frames)
    return frame_index % frames < on


@dataclass(frozen=True)
class FrameStats:
    frames: int = 0
    dropped: int = 0  # display refreshes we missed: each one shifts every flicker's phase
    slow_frames: int = 0  # frames longer than SLOW_FRAME_S
    max_frame_s: float = 0.0
    total_s: float = 0.0


def update_frame_stats(stats: FrameStats, frame_s: float, display_hz: int = DISPLAY_HZ) -> FrameStats:
    """Return new stats including one more frame that took frame_s seconds (from flip to flip)."""
    refreshes = int(frame_s * display_hz + 0.5)  # how many display refreshes this frame actually spanned
    return replace(
        stats,
        frames=stats.frames + 1,
        dropped=stats.dropped + max(0, refreshes - 1),
        slow_frames=stats.slow_frames + (1 if frame_s > SLOW_FRAME_S else 0),
        max_frame_s=max(stats.max_frame_s, frame_s),
        total_s=stats.total_s + frame_s,
    )


def format_frame_summary(stats: FrameStats) -> str:
    fps = stats.frames / stats.total_s if stats.total_s > 0 else 0.0
    return (f"summary: seconds={stats.total_s:.1f} frames={stats.frames} mean_fps={fps:.1f} "
            f"dropped={stats.dropped} slow_frames={stats.slow_frames} max_frame_ms={stats.max_frame_s * 1000:.1f}")
