"""Live jaw-clench confirmation test. HUMANS run it with the real board; agents only use --synthetic.

    python -m bci.jaw_live --synthetic          # practice: BrainFlow fake board + scripted fake clenches
    python -m bci.jaw_live --wifi               # Cyton + Wi-Fi shield (laptop on the OpenBCI-xxxx network)
    python -m bci.jaw_live --dongle /dev/cu.usbserial-XXXX   # Cyton + USB dongle (more stable than Wi-Fi)

Steps it guides you through: 10 s relaxed -> 3 clenches (1 s each) -> threshold -> live: every clench held
for 0.3 s prints CONFIRM. Pass: 10 clenches -> 10 CONFIRMs; 30 s talking / blinking -> 0 CONFIRMs.
Close the OpenBCI GUI first: only one program can hold the board.
"""

from __future__ import annotations

import argparse
import queue
import sys
import threading
import time
from collections.abc import Callable

import numpy as np

from bci.jaw import WINDOW_S, JawState, calibrate_threshold, emg_rms, update_jaw

RELAX_S, CLENCH_S, CLENCH_REST_S, N_CLENCHES = 10.0, 1.0, 2.0, 3
WIFI_IP, WIFI_PORT = "192.168.4.1", 6677


class JawStream:
    """Board chunks of any size -> 0.1 s windows -> calibration or live confirmations."""

    def __init__(self, fs: float) -> None:
        self.fs, self.n = fs, int(round(WINDOW_S * fs))
        self._buffer = np.zeros((0, 0))
        self._calibration: dict[str, list[float]] = {"relaxed": [], "clench": []}
        self.threshold: float | None = None
        self._state, self._t = JawState(), 0.0

    def _windows(self, chunk: np.ndarray):
        chunk = np.atleast_2d(chunk)
        self._buffer = chunk if self._buffer.size == 0 else np.concatenate([self._buffer, chunk], axis=1)
        while self._buffer.shape[1] >= self.n:
            window, self._buffer = self._buffer[:, :self.n], self._buffer[:, self.n:]
            yield window

    def collect(self, phase: str, chunk: np.ndarray) -> None:
        """Calibration data: phase is 'relaxed' or 'clench'."""
        self._calibration[phase] += [emg_rms(w, self.fs) for w in self._windows(chunk)]

    def finish_calibration(self) -> float:
        relaxed, clenches = self._calibration["relaxed"], self._calibration["clench"]
        # Only the strongest third of the clench windows: the clench prompt includes reaction time.
        strongest = sorted(clenches)[-max(1, len(clenches) // 3):]
        self.threshold = calibrate_threshold(relaxed, strongest)
        self._buffer = np.zeros((0, 0))
        return self.threshold

    def push(self, chunk: np.ndarray) -> list[float]:
        """Live data. Returns the stream times of any confirmed clenches."""
        fired = []
        for window in self._windows(chunk):
            self._t += WINDOW_S
            if self.threshold is None:
                continue
            self._state, hit = update_jaw(self._state, emg_rms(window, self.fs), self._t, self.threshold)
            if hit:
                fired.append(self._t)
        return fired


def connect_board(mode: str, port: str | None = None, channels: tuple[int, ...] = (1, 2)):
    """mode: 'synthetic' (no hardware), 'wifi' (Cyton + Wi-Fi shield) or 'dongle' (Cyton + USB dongle on `port`).
    Returns (board, eeg rows to use, sampling rate). HUMANS run wifi/dongle; agents only synthetic."""
    from brainflow.board_shim import BoardIds, BoardShim, BrainFlowInputParams

    params = BrainFlowInputParams()
    if mode == "synthetic":
        board_id = BoardIds.SYNTHETIC_BOARD.value
    elif mode == "wifi":
        board_id = BoardIds.CYTON_WIFI_BOARD.value
        params.ip_address, params.ip_port = WIFI_IP, WIFI_PORT
    elif mode == "dongle":
        board_id = BoardIds.CYTON_BOARD.value
        params.serial_port = port
    else:
        raise ValueError(f"unknown board mode {mode!r}")
    board = BoardShim(board_id, params)
    board.prepare_session()
    board.start_stream()
    eeg = BoardShim.get_eeg_channels(board_id)
    # Only channels with an electrode: an unplugged channel is pure noise and could fake or hide a clench.
    rows = [eeg[c - 1] for c in channels]
    return board, rows, BoardShim.get_sampling_rate(board_id)


def connect(args):
    mode = "synthetic" if args.synthetic else "wifi" if args.wifi else "dongle"
    return connect_board(mode, args.dongle, parse_channels(args.channels))


def parse_channels(text: str) -> tuple[int, ...]:
    """'1' or '1,2' -> (1,) / (1, 2). Cyton channels are 1-8 (N1P..N8P)."""
    channels = tuple(int(c) for c in text.split(",") if c.strip())
    if not channels or any(c < 1 or c > 8 for c in channels):
        raise ValueError(f"channels must be 1-8, got {text!r}")
    return channels


def fake_clench(fs: float, seconds: float, channels: int) -> np.ndarray:
    """Practice mode only: a broadband 40-120 Hz burst like real jaw EMG, added to the fake board's signal."""
    t = np.arange(int(seconds * fs)) / fs
    freqs = np.random.default_rng().uniform(40, min(120, fs / 2 - 5), 25)
    burst = sum(np.sin(2 * np.pi * f * t + np.random.default_rng().uniform(0, 6.3)) for f in freqs)
    return np.tile(burst / burst.std() * 150.0, (channels, 1))


def read(board, rows, fs, seconds: float, synthetic_clench: bool = False) -> np.ndarray:
    """Collect `seconds` of data from the board (draining its buffer as it goes)."""
    end, parts = time.monotonic() + seconds, []
    while time.monotonic() < end:
        time.sleep(0.05)
        data = board.get_board_data()[rows]
        if data.size:
            parts.append(data + (fake_clench(fs, data.shape[1] / fs, len(rows)) if synthetic_clench else 0))
    return np.concatenate(parts, axis=1) if parts else np.zeros((len(rows), 0))


class JawConfirmSource:
    """Jaw clenches -> confirm events, for the object-selection screen. Calibrate (relax + 3 clenches), then a
    background thread reads the board and queues one event per clench. take() is polled by the UI loop."""

    def __init__(self, mode: str, port: str | None = None, relax_s: float = RELAX_S, clench_s: float = CLENCH_S,
                 rest_s: float = CLENCH_REST_S, channels: tuple[int, ...] = (1, 2)) -> None:
        self.mode = mode
        self._board, self._rows, self._fs = connect_board(mode, port, channels)
        self._stream = JawStream(self._fs)
        self._durations = (relax_s, clench_s, rest_s)
        self._events: queue.Queue = queue.Queue()
        self._stop = threading.Event()
        self._fake_until = 0.0  # practice mode only: add a fake clench to data until this time
        self._thread = threading.Thread(target=self._run, name="jaw-confirm", daemon=True)

    def calibrate(self, show: Callable[[str], None]) -> float:
        """Guided calibration; `show` displays each instruction. Raises ValueError if contact is too poor."""
        relax_s, clench_s, rest_s = self._durations
        show(f"Relax your jaw, teeth apart ({relax_s:.0f} s)")
        self._stream.collect("relaxed", read(self._board, self._rows, self._fs, relax_s))
        for i in range(N_CLENCHES):
            show(f"CLENCH your jaw now ({i + 1}/{N_CLENCHES})")
            self._stream.collect("clench", read(self._board, self._rows, self._fs, clench_s,
                                                synthetic_clench=self.mode == "synthetic"))
            show("Relax")
            read(self._board, self._rows, self._fs, rest_s)
        return self._stream.finish_calibration()

    def start(self) -> None:
        self._thread.start()

    def inject_fake_clench(self, seconds: float = 0.6) -> None:
        """Practice mode (synthetic board): pretend the rider clenches for `seconds`."""
        self._fake_until = time.monotonic() + seconds

    def take(self) -> bool:
        """True if at least one clench was confirmed since the last call."""
        fired = False
        while True:
            try:
                self._events.get_nowait()
                fired = True
            except queue.Empty:
                return fired

    def stop(self) -> None:
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join(timeout=1.0)
        try:
            self._board.stop_stream()
            self._board.release_session()
        except Exception:  # already released or the board vanished: nothing left to clean up
            pass

    def _run(self) -> None:
        while not self._stop.is_set():
            time.sleep(0.05)
            data = self._board.get_board_data()[self._rows]
            if not data.size:
                continue
            if self.mode == "synthetic" and time.monotonic() < self._fake_until:
                data = data + fake_clench(self._fs, data.shape[1] / self._fs, len(self._rows))
            for _ in self._stream.push(data):
                self._events.put(time.monotonic())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Live jaw-clench confirmation test")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--synthetic", action="store_true", help="fake board + scripted fake clenches (no hardware)")
    mode.add_argument("--wifi", action="store_true", help="Cyton with Wi-Fi shield (HUMANS only)")
    mode.add_argument("--dongle", metavar="PORT", help="Cyton with USB dongle, e.g. /dev/cu.usbserial-DM0xxxx (HUMANS only)")
    parser.add_argument("--seconds", type=float, default=60.0, help="length of the live part")
    parser.add_argument("--channels", default="1,2", help="Cyton channels with an electrode, e.g. 1 or 1,2")
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)

    board, rows, fs = connect(args)
    print(f"connected: {fs} Hz, channels {rows}")
    stream = JawStream(fs)
    try:
        print(f"1) RELAX your jaw, teeth apart, for {RELAX_S:.0f} s ...")
        stream.collect("relaxed", read(board, rows, fs, RELAX_S))
        for i in range(N_CLENCHES):
            print(f"2) CLENCH {i + 1}/{N_CLENCHES} now (hold)")
            stream.collect("clench", read(board, rows, fs, CLENCH_S, synthetic_clench=args.synthetic))
            print("   relax")
            read(board, rows, fs, CLENCH_REST_S)
        try:
            threshold = stream.finish_calibration()
        except ValueError as error:
            print(f"CALIBRATION FAILED: {error}")
            return 2
        print(f"calibrated (threshold {threshold:.1f}). 3) LIVE: clench to confirm; Ctrl+C to stop.")
        confirms, start = 0, time.monotonic()
        while time.monotonic() - start < args.seconds:
            elapsed = time.monotonic() - start
            # Practice mode: a fake 0.6 s clench every 5 s so the whole flow can be seen without a board.
            fake = args.synthetic and (elapsed % 5.0) < 0.6
            for _ in stream.push(read(board, rows, fs, 0.1, synthetic_clench=fake)):
                confirms += 1
                print(f"\a   CONFIRM #{confirms} at {elapsed:5.1f} s")
    except KeyboardInterrupt:
        pass
    finally:
        board.stop_stream()
        board.release_session()
    print(f"summary: confirms={confirms}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
