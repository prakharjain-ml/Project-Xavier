"""Run the real pygame loop on SDL's off-screen 'dummy' driver: proves the logic (warning gate, loop, summary),
NOT the 60 FPS timing. The timing gate needs a human run on the MacBook screen."""

import os
import queue
import re

os.environ["SDL_VIDEODRIVER"] = "dummy"  # must be set before pygame opens a display
os.environ["SDL_AUDIODRIVER"] = "dummy"

from interface.flicker import main, offer_latest  # noqa: E402
from shared.protocol import ControlStatus, State, Target  # noqa: E402


def frames_of(capsys) -> int:
    """Exact 'frames=N' value (a plain substring test would also match 'slow_frames=0')."""
    line = [ln for ln in capsys.readouterr().out.splitlines() if ln.startswith("summary:")][-1]
    return int(re.search(r"(?<!\w)frames=(\d+)", line).group(1))


def test_no_flicker_before_space(capsys):
    assert main(["--windowed", "--seconds", "0.4"], start_events=[]) == 0
    assert frames_of(capsys) == 0  # never got past the photosensitivity warning


def test_flicker_runs_after_space(capsys):
    assert main(["--windowed", "--seconds", "0.6", "--fake-status"], start_events=["space"]) == 0
    assert frames_of(capsys) > 10


def test_single_target_mode_runs(capsys):
    assert main(["--windowed", "--single", "12", "--seconds", "0.4"], start_events=["space"]) == 0
    assert frames_of(capsys) > 5


def test_single_target_rejects_inexact_frequency():
    assert main(["--windowed", "--single", "11", "--seconds", "0.2"], start_events=["space"]) == 2


def test_escape_on_warning_screen_quits_without_flicker(capsys):
    assert main(["--windowed", "--seconds", "2"], start_events=["escape"]) == 0
    assert frames_of(capsys) == 0


def test_offer_latest_keeps_only_newest():
    q = queue.Queue(maxsize=1)
    old = ControlStatus(State.STOPPED, Target.NONE, 0.0)
    new = ControlStatus(State.DWELLING, Target.FWD, 0.5)
    offer_latest(q, old)
    offer_latest(q, new)  # must not block or raise on a full queue
    assert q.get_nowait() == new and q.empty()


def test_loop_is_paced_near_60_fps_even_without_real_vsync(capsys):
    # The dummy driver claims vsync but does not pace; the runtime check must fall back to clock pacing.
    assert main(["--windowed", "--seconds", "2.0"], start_events=["space"]) == 0
    frames = frames_of(capsys)
    # The danger is running TOO FAST (unpaced: arrows flicker at the wrong rate) -> strict upper bound.
    # Running slower under CPU load is reported as dropped frames, so the lower bound only checks it ran.
    assert frames <= 130, f"{frames} frames in 2 s: loop is NOT paced (faster than 60 FPS)"
    assert frames >= 30, f"only {frames} frames in 2 s: loop barely ran"
