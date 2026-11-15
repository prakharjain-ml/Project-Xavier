"""Train or run the two-channel jaw–temple clench detector."""
import argparse
from collections import deque
from pathlib import Path
import time

import joblib
import numpy as np
import pandas as pd
from brainflow.board_shim import BoardIds, BoardShim, BrainFlowInputParams
from scipy.signal import periodogram
from sklearn.linear_model import LogisticRegression

RATE = 1000
WINDOW = 500
MODEL_FILE = Path(__file__).with_name("jaw_temple.joblib")
HOLDOUT = {"clench_5", "clench_6", "relax_5", "relax_6"}


def band_rms(two_channels):
    jaw, temple = two_channels
    hz, power = periodogram(jaw - temple, fs=RATE, window="hann")
    band = (hz >= 80) & (hz <= 200) & (abs(hz - 120) > 5) & (abs(hz - 180) > 5)
    return np.sqrt(power[band].sum() * (hz[1] - hz[0]))


def model_input(amplitudes):
    return np.log1p(np.asarray(amplitudes).reshape(-1, 1))


def calibrate(model, recording):
    # This optional recording must start with 10 s rest, then 10 s clench.
    columns = ["jaw_uv", "temple_uv", "elapsed_s"]
    if list(pd.read_csv(recording, sep="\t", nrows=0).columns) == columns:
        raw = pd.read_csv(recording, sep="\t", usecols=columns).dropna()
    else:
        # BrainFlow's native export uses board rows 1, 2 and 22 for EMG and time.
        raw = pd.read_csv(recording, sep="\t", header=None, usecols=[1, 2, 22]).dropna()
        raw.columns = columns
    elapsed = raw.elapsed_s.to_numpy() - raw.elapsed_s.iloc[0]
    signals = raw[["jaw_uv", "temple_uv"]].to_numpy().T
    classes = [[], []]
    for start in range(0, len(raw) - WINDOW + 1, WINDOW):
        first, last = elapsed[start], elapsed[start + WINDOW - 1]
        # Leave a second around each cue so transitions and startup are excluded.
        for label, lower, upper in ((0, 1, 9), (1, 11, 19)):
            if lower <= first and last <= upper:
                classes[label].append(band_rms(signals[:, start:start + WINDOW]))
    if min(map(len, classes)) < 6:
        raise ValueError("Calibration needs complete rest and clench periods.")
    rest, clench = [np.median(model_input(values)) for values in classes]
    if clench <= rest:
        raise ValueError("Calibration clench amplitude did not exceed rest.")
    midpoint = (rest + clench) / 2
    model.intercept_[0] = -model.coef_[0, 0] * midpoint
    print(f"Calibrated jaw–temple cutoff: {np.expm1(midpoint):.1f} µV RMS")


def train(samples_path, model_path, calibration=None):
    rows = pd.read_csv(samples_path)
    amplitudes, labels, trials = [], [], []
    for window_id, group in rows.groupby("window_id", sort=False):
        group = group.sort_values("sample_offset")
        if not np.array_equal(group.sample_offset, np.arange(WINDOW)):
            raise ValueError(f"Expected a complete 500-sample window in {window_id}")
        raw = group[["ch1_raw_uv", "ch2_raw_uv"]].to_numpy().T
        amplitudes.append(band_rms(raw))
        labels.append(group.label.iloc[0])
        trials.append(group.trial_id.iloc[0])
    x, y = model_input(amplitudes), np.asarray(labels)
    test = np.isin(trials, list(HOLDOUT))
    model = LogisticRegression(class_weight="balanced", random_state=42)
    model.fit(x[~test], y[~test])
    if test.any():
        predicted = model.predict(x[test])
        for label, name in [(0, "Relax"), (1, "Clench")]:
            mask = y[test] == label
            print(f"{name}: {sum(predicted[mask] == label)}/{mask.sum()} held-out windows correct")
    if calibration:
        calibrate(model, calibration)
    joblib.dump(model, model_path)
    print(f"Saved {model_path}")


class Detector:
    def __init__(self, model):
        self.model = model
        self.history = deque(maxlen=3)
        self.buffer = np.empty((2, 0))

    def update(self, channels):
        self.buffer = np.concatenate((self.buffer, channels), axis=1)
        while self.buffer.shape[1] >= WINDOW:
            amplitude = band_rms(self.buffer[:, :WINDOW])
            self.buffer = self.buffer[:, WINDOW:]
            self.history.append(amplitude)
            if len(self.history) == self.history.maxlen:
                smoothed = np.median(self.history)
                score = self.model.predict_proba(model_input([smoothed]))[0, 1]
                yield amplitude, score


def live(model_path, ip, port):
    detector = Detector(joblib.load(model_path))
    params = BrainFlowInputParams()
    params.ip_address, params.ip_port, params.timeout = ip, port, 10
    board_id = BoardIds.CYTON_WIFI_BOARD.value
    board = BoardShim(board_id, params)
    channels = BoardShim.get_emg_channels(board_id)[:2]
    print(f"Connecting to Cyton WiFi at {ip}...", flush=True)
    board.prepare_session()
    try:
        rate = board.get_board_sampling_rate()
        if rate != RATE:
            raise RuntimeError(f"Expected {RATE} Hz, received {rate} Hz.")
        board.start_stream()
        try:
            print("Jaw–temple detector running. CH1 jaw, CH2 temple. Ctrl+C to stop.", flush=True)
            last_data = time.monotonic()
            while True:
                time.sleep(0.05)
                data = board.get_board_data()
                if data.shape[1]:
                    last_data = time.monotonic()
                    for amplitude, score in detector.update(data[channels]):
                        state = "CLENCHING" if score >= 0.5 else "RELAXED"
                        print(f"{state:10} | clench score {score:.0%} | jaw–temple {amplitude:.1f} µV RMS", flush=True)
                elif time.monotonic() - last_data > 10:
                    raise RuntimeError("No board samples for 10 seconds. Check the shield connection.")
        finally:
            board.stop_stream()
    finally:
        board.release_session()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--train", metavar="SAMPLES_CSV", help="fit using the original labeled raw sample windows")
    parser.add_argument("--calibration", metavar="BRAINFLOW_CSV", help="with --train, set the cutoff from 10 s rest then 10 s clench at recording start")
    parser.add_argument("--model", type=Path, default=MODEL_FILE)
    parser.add_argument("--ip", default="192.168.4.1")
    parser.add_argument("--port", type=int, default=6789)
    args = parser.parse_args()
    if args.train:
        train(args.train, args.model, args.calibration)
    else:
        try:
            live(args.model, args.ip, args.port)
        except KeyboardInterrupt:
            print("\nStopped.")
