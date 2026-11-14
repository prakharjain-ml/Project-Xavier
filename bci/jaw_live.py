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
import sys
import time

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


def connect(args):
    from brainflow.board_shim import BoardIds, BoardShim, BrainFlowInputParams

    params = BrainFlowInputParams()
    if args.synthetic:
        board_id = BoardIds.SYNTHETIC_BOARD.value
    elif args.wifi:
        board_id = BoardIds.CYTON_WIFI_BOARD.value
        params.ip_address, params.ip_port = WIFI_IP, WIFI_PORT
    else:
        board_id = BoardIds.CYTON_BOARD.value
        params.serial_port = args.dongle
    board = BoardShim(board_id, params)
    board.prepare_session()
    board.start_stream()
    rows = BoardShim.get_eeg_channels(board_id)[:2]  # O1, O2 (channels 1-2); any channel sees jaw EMG
    return board, rows, BoardShim.get_sampling_rate(board_id)


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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Live jaw-clench confirmation test")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--synthetic", action="store_true", help="fake board + scripted fake clenches (no hardware)")
    mode.add_argument("--wifi", action="store_true", help="Cyton with Wi-Fi shield (HUMANS only)")
    mode.add_argument("--dongle", metavar="PORT", help="Cyton with USB dongle, e.g. /dev/cu.usbserial-DM0xxxx (HUMANS only)")
    parser.add_argument("--seconds", type=float, default=60.0, help="length of the live part")
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
