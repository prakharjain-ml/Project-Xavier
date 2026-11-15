"""Jaw-clench flash test: a black screen that turns WHITE for 1 s every time the board sees a clench.

Purpose: find exactly which link breaks between the electrodes and our code. The screen (and the terminal,
once a second) shows each stage in order, so the first red line is where it is broken:

    1 BOARD    BrainFlow opened the Cyton                    (fails: wrong port, GUI still open, no Wi-Fi)
    2 DATA     samples are arriving every second             (fails: board connected but not streaming)
    3 SIGNAL   samples are not flat or railed                (fails: electrode / ear clip not touching)
    4 LEVEL    muscle-band level (40-200 Hz) vs the relaxed baseline measured in the first 3 s
    5 CLENCH   level went above the threshold -> white flash (fails: threshold too high -> press DOWN)

It deliberately skips the real detector's calibration and 0.3 s hold (bci/jaw_live.py), so if THIS flashes
but the demo does not confirm, the problem is in the detector settings, not the headset or the reading.

HUMANS run the real board. Close the OpenBCI GUI first (only one program can hold the board):
    python -m tools.jaw_flash                                     # Cyton + Wi-Fi shield (the default)
    python -m tools.jaw_flash --synthetic                         # no hardware: SPACE = fake clench
Keys: UP / DOWN raise / lower the threshold, R re-measures the relaxed baseline, ESC quits.
"""

from __future__ import annotations

import argparse
import time
from datetime import datetime
from pathlib import Path
from dataclasses import dataclass, field

import numpy as np
import pygame

from bci.jaw import MIN_CLENCH_S, WINDOW_S, dead_reason, emg_rms
from bci.jaw_live import connect_board, fake_clench, parse_channels
from tools import jaw_flash_view

FLASH_S = 1.0          # how long the screen stays white after a clench
BASELINE_S = 3.0       # relaxed jaw at start: the median muscle level here is "rest"
START_RATIO = 3.0      # threshold = this x the relaxed level (the real detector requires at least 3x too)
RATIO_STEP = 0.5       # UP / DOWN change the ratio by this much
NO_DATA_S = 2.0        # no new samples for this long = stage 2 is broken
FAKE_CLENCH_S = 0.6    # synthetic mode: how long one SPACE press "clenches"
PRINT_EVERY_S = 1.0    # terminal status line rate
FPS = 60
CONNECT_TRIES = 4       # stage 1 attempts before giving up
CONNECT_RETRY_S = 3.0   # pause between attempts (lets the shield finish the last request)
HOLD_WINDOWS = round(MIN_CLENCH_S / WINDOW_S)  # 3 x 0.1 s: above threshold for 0.3 s, same rule as the real detector
LOG_DIR = Path("data/raw/sessions")  # git-ignored; one CSV of levels + one .npy of raw samples per run


@dataclass
class Probe:
    """Everything the screen shows. Updated once per frame from the newest board data."""
    fs: float
    n: int                                   # samples per 0.1 s window
    buffer: np.ndarray = field(default_factory=lambda: np.zeros((0, 0)))
    total_samples: int = 0
    last_data_at: float = field(default_factory=time.monotonic)
    rate: float = 0.0                        # samples per second, measured
    problem: str | None = None               # stage 3: why the newest window is untrustworthy
    level: float = 0.0                       # stage 4: newest window's muscle level (uV), loudest channel
    channel_levels: tuple[float, ...] = ()   # the same level per channel: shows WHICH electrode is spiking
    above: int = 0                           # how many windows in a row have been above the threshold
    log_rows: list[str] = field(default_factory=list)       # one CSV line per window, written at the end
    raw_parts: list[np.ndarray] = field(default_factory=list)  # every raw sample, saved at the end
    baseline: list[float] = field(default_factory=list)
    relaxed: float | None = None             # median of the baseline windows, once BASELINE_S is collected
    ratio: float = START_RATIO
    clenches: int = 0
    white_until: float = 0.0

    @property
    def threshold(self) -> float | None:
        return None if self.relaxed is None else self.relaxed * self.ratio


def new_windows(probe: Probe, chunk: np.ndarray):
    """Append the new samples and hand back every complete 0.1 s window (leftover samples wait for the next)."""
    probe.buffer = chunk if probe.buffer.size == 0 else np.concatenate([probe.buffer, chunk], axis=1)
    while probe.buffer.shape[1] >= probe.n:
        window, probe.buffer = probe.buffer[:, :probe.n], probe.buffer[:, probe.n:]
        yield window


def judge_window(probe: Probe, window: np.ndarray, now: float) -> None:
    """Stages 3-5 for one window. A clench must stay above the threshold for HOLD_WINDOWS windows in a row
    (0.3 s): single 0.1 s spikes from cable sway or Wi-Fi hiccups are common and are not clenches."""
    probe.problem = dead_reason(window)
    if probe.problem is not None:
        probe.above = 0
        probe.log_rows.append(f"{now:.3f},,,,{probe.problem.replace(',', ';')},0")
        return
    probe.channel_levels = tuple(emg_rms(window[i:i + 1], probe.fs) for i in range(window.shape[0]))
    probe.level = max(probe.channel_levels)  # same as emg_rms(window): the loudest channel decides
    fired = 0
    if probe.relaxed is None:
        probe.baseline.append(probe.level)
        if len(probe.baseline) * WINDOW_S >= BASELINE_S:
            probe.relaxed = max(float(np.median(probe.baseline)), 1e-6)
            print(f"[baseline] relaxed level {probe.relaxed:.2f} uV -> threshold {probe.threshold:.2f} uV")
    else:
        probe.above = probe.above + 1 if probe.level > probe.threshold else 0
        if probe.above >= HOLD_WINDOWS and now >= probe.white_until:
            fired, probe.above = 1, 0
            probe.clenches += 1
            probe.white_until = now + FLASH_S
            loudest = int(np.argmax(probe.channel_levels)) + 1
            print(f"[CLENCH #{probe.clenches}] level {probe.level:.1f} uV = {probe.level / probe.relaxed:.1f}x "
                  f"relaxed, loudest channel {loudest} (per channel: "
                  f"{', '.join(f'{v:.1f}' for v in probe.channel_levels)} uV)")
    levels = ",".join(f"{v:.2f}" for v in (probe.channel_levels + (0.0, 0.0))[:2])
    probe.log_rows.append(f"{now:.3f},{levels},{probe.threshold or 0:.2f},,{fired}")


def poll_board(probe: Probe, board, rows, fake_until: float, now: float) -> None:
    """Stage 2: drain whatever the board has buffered since the last frame (non-blocking)."""
    data = board.get_board_data()[rows]
    if not data.size:
        return
    if now < fake_until:  # synthetic mode only: SPACE was pressed
        data = data + fake_clench(probe.fs, data.shape[1] / probe.fs, len(rows))
    probe.total_samples += data.shape[1]
    probe.raw_parts.append(data)
    probe.last_data_at = now
    for window in new_windows(probe, data):
        judge_window(probe, window, now)


def stage_lines(probe: Probe, board_text: str, now: float) -> list[tuple[str, bool]]:
    """(text, ok) for each stage. The first not-ok line is where the chain is broken."""
    stale = now - probe.last_data_at
    data_ok = probe.total_samples > 0 and stale < NO_DATA_S
    data = (f"2 DATA    {probe.rate:.0f} samples/s (board says {probe.fs:.0f})" if data_ok
            else f"2 DATA    NO SAMPLES for {stale:.0f} s - board connected but not streaming")
    signal = "3 SIGNAL  ok" if probe.problem is None else f"3 SIGNAL  {probe.problem}"
    if probe.relaxed is None:
        level = (f"4 LEVEL   keep jaw RELAXED: measuring rest "
                 f"{len(probe.baseline) * WINDOW_S:.1f}/{BASELINE_S:.0f} s  (now {probe.level:.1f} uV)")
    else:
        per_channel = "  ".join(f"ch{i + 1} {v / probe.relaxed:.1f}x" for i, v in enumerate(probe.channel_levels))
        level = (f"4 LEVEL   {probe.level / probe.relaxed:.1f}x relaxed ({per_channel})   "
                 f"threshold {probe.ratio:.1f}x, held {MIN_CLENCH_S:.1f} s")
    return [(f"1 BOARD   {board_text}", True), (data, data_ok), (signal, probe.problem is None),
            (level, probe.relaxed is not None), (f"5 CLENCH  flashes so far: {probe.clenches}", True)]


def draw(screen, font, probe: Probe, lines: list[tuple[str, bool]], now: float, synthetic: bool = False) -> None:
    """Themed screen (tools/jaw_flash_view.py); the whole screen still turns white for FLASH_S on each clench.
    `font` is unused now (kept so callers need not change)."""
    w, h = screen.get_size()
    picture = jaw_flash_view.render(probe, lines, now, w, h, synthetic)
    screen.blit(pygame.image.frombuffer(picture.tobytes(), picture.size, "RGB"), (0, 0))
    pygame.display.flip()


def handle_keys(probe: Probe, synthetic: bool, fake_until: float, now: float) -> tuple[bool, float]:
    """Returns (keep running, new fake-clench end time)."""
    for event in pygame.event.get():
        if event.type == pygame.QUIT or (event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE):
            return False, fake_until
        if event.type != pygame.KEYDOWN:
            continue
        if event.key == pygame.K_UP:
            probe.ratio += RATIO_STEP
        elif event.key == pygame.K_DOWN:
            probe.ratio = max(1.0 + RATIO_STEP, probe.ratio - RATIO_STEP)
        elif event.key == pygame.K_r:
            probe.baseline, probe.relaxed = [], None
            print("[baseline] re-measuring: keep your jaw relaxed")
        elif event.key == pygame.K_SPACE and synthetic:
            fake_until = now + FAKE_CLENCH_S
    return True, fake_until


def run(board, rows, fs, board_text: str, synthetic: bool, windowed: bool, max_s: float | None) -> None:
    pygame.init()
    screen = pygame.display.set_mode((1280, 800) if windowed else (0, 0), 0 if windowed else pygame.FULLSCREEN)
    pygame.display.set_caption("jaw flash test")
    font, clock = pygame.font.SysFont("menlo", 26), pygame.time.Clock()
    probe = Probe(fs=fs, n=int(round(WINDOW_S * fs)))
    started = time.monotonic()
    fake_until, rate_mark, printed_at = 0.0, (started, 0), started  # first print once a rate exists
    running = True
    while running and (max_s is None or time.monotonic() - started < max_s):
        now = time.monotonic()
        running, fake_until = handle_keys(probe, synthetic, fake_until, now)
        poll_board(probe, board, rows, fake_until, now)
        if now - rate_mark[0] >= 1.0:  # samples-per-second over the last second
            probe.rate = (probe.total_samples - rate_mark[1]) / (now - rate_mark[0])
            rate_mark = (now, probe.total_samples)
        lines = stage_lines(probe, board_text, now)
        if now - printed_at >= PRINT_EVERY_S:
            printed_at = now
            print(" | ".join(" ".join(text.split()) for text, _ in lines[1:]))
        draw(screen, font, probe, lines, now, synthetic)
        clock.tick(FPS)
    pygame.quit()
    save_log(probe)


def save_log(probe: Probe) -> None:
    """Write this run to data/raw/sessions/ so it can be analysed afterwards (the laptop is offline on the
    headset Wi-Fi, so nobody can watch live). CSV: one line per 0.1 s window. NPY: raw uV, channels x samples."""
    stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        csv_path, raw_path = LOG_DIR / f"jaw_flash_{stamp}.csv", LOG_DIR / f"jaw_flash_{stamp}_raw.npy"
        header = f"# fs={probe.fs} relaxed_uV={probe.relaxed} ratio={probe.ratio}\n" \
                 "t,ch1_uV,ch2_uV,threshold_uV,problem,flash\n"
        csv_path.write_text(header + "\n".join(probe.log_rows) + "\n")
        if probe.raw_parts:
            np.save(raw_path, np.concatenate(probe.raw_parts, axis=1))
        print(f"[log] saved {csv_path} and {raw_path.name}")
    except OSError as error:  # a full disk must not hide the test result that was already printed
        print(f"[log] could not save the session log: {error}")


def connect_with_retries(mode: str, port: str | None, channels: tuple[int, ...]):
    """Stage 1. The Wi-Fi shield often misses one command right after the OpenBCI GUI let go of it
    ("BOARD_WRITE_ERROR:4 ... request failed"), so try a few times before calling it broken."""
    for attempt in range(1, CONNECT_TRIES + 1):
        try:
            return connect_board(mode, port, channels)
        except Exception as error:  # BrainFlow raises BrainFlowError; say exactly what it said
            print(f"[1 BOARD] attempt {attempt}/{CONNECT_TRIES} FAILED: {error}")
            if attempt < CONNECT_TRIES:
                time.sleep(CONNECT_RETRY_S)
    print("[1 BOARD] GAVE UP. The shield answers but the Cyton under it does not:\n"
          "  -> slide the Cyton switch OFF, wait 5 s, back to PC, wait for the shield light, rejoin the\n"
          "     OpenBCI-xxxx Wi-Fi, and run again. Still failing? Charge / swap the battery.")
    raise SystemExit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    source = parser.add_mutually_exclusive_group()  # nothing given = Wi-Fi
    source.add_argument("--synthetic", action="store_true", help="BrainFlow fake board (no hardware)")
    source.add_argument("--wifi", action="store_true", help="Cyton + Wi-Fi shield (default)")
    source.add_argument("--dongle", metavar="PORT", help="only if using the USB dongle instead of Wi-Fi")
    parser.add_argument("--channels", default="1,2", help="Cyton channels with jaw electrodes (default 1,2)")
    parser.add_argument("--windowed", action="store_true", help="window instead of full screen")
    parser.add_argument("--seconds", type=float, default=None, help="quit after this long (for scripted checks)")
    args = parser.parse_args()
    mode = "synthetic" if args.synthetic else "dongle" if args.dongle else "wifi"
    channels = parse_channels(args.channels)
    print(f"[1 BOARD] connecting: {mode} {args.dongle or ''} channels {channels} ...")
    board, rows, fs = connect_with_retries(mode, args.dongle, channels)
    board_text = f"connected ({mode}, {fs} Hz, channels {','.join(map(str, channels))}, rows {rows})"
    print(f"[1 BOARD] {board_text}")
    try:
        run(board, rows, fs, board_text, args.synthetic, args.windowed, args.seconds)
    finally:
        board.stop_stream()
        board.release_session()
        print("[1 BOARD] released")


if __name__ == "__main__":
    main()
