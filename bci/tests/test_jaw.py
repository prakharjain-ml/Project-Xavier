"""Jaw-clench confirmation detector (bci/jaw.py). Synthetic signals at the real board rate (1000 Hz)."""

import numpy as np
import pytest

from bci.jaw import (
    MIN_CLENCH_S,
    REFRACTORY_S,
    WINDOW_S,
    JawState,
    calibrate_threshold,
    emg_rms,
    update_jaw,
)

FS = 1000
rng = np.random.default_rng(0)


def eeg(seconds, channels=2, uv=15.0):
    """Background EEG-like noise plus strong 60 Hz hum (as seen on our board)."""
    t = np.arange(int(seconds * FS)) / FS
    return rng.normal(0, uv, (channels, t.size)) + 200 * np.sin(2 * np.pi * 60 * t)


def clench(seconds, channels=2, uv=120.0):
    """Muscle burst: broadband 40-200 Hz energy."""
    from scipy.signal import butter, sosfiltfilt

    raw = rng.normal(0, 1, (channels, int(seconds * FS)))
    burst = sosfiltfilt(butter(4, [40, 200], btype="band", fs=FS, output="sos"), raw, axis=1)
    return burst / burst.std() * uv


def windows(signal):
    n = int(WINDOW_S * FS)
    return [signal[:, i:i + n] for i in range(0, signal.shape[1] - n + 1, n)]


def run(signal, threshold, start_t=0.0):
    state, fired = JawState(), []
    for i, w in enumerate(windows(signal)):
        state, hit = update_jaw(state, emg_rms(w, FS), start_t + (i + 1) * WINDOW_S, threshold)
        if hit:
            fired.append(start_t + (i + 1) * WINDOW_S)
    return fired


def test_clench_is_much_stronger_than_relaxed_even_with_mains_hum():
    relaxed = np.median([emg_rms(w, FS) for w in windows(eeg(5))])
    clenched = np.median([emg_rms(w, FS) for w in windows(eeg(2) + clench(2))])
    assert clenched > 5 * relaxed  # the 60 Hz hum was removed, so it does not look like a clench


def test_threshold_sits_between_relaxed_and_clench():
    relaxed = [emg_rms(w, FS) for w in windows(eeg(10))]
    clenches = [emg_rms(w, FS) for w in windows(eeg(1) + clench(1))]
    threshold = calibrate_threshold(relaxed, clenches)
    assert max(relaxed) < threshold < min(clenches)


def test_calibration_refuses_when_clench_is_not_clearly_stronger():
    with pytest.raises(ValueError, match="clench"):
        calibrate_threshold([10.0] * 50, [15.0] * 10)  # only 1.5x: electrodes too poor to trust


def test_half_second_clench_fires_once():
    relaxed = [emg_rms(w, FS) for w in windows(eeg(10))]
    threshold = calibrate_threshold(relaxed, [emg_rms(w, FS) for w in windows(eeg(1) + clench(1))])
    signal = np.concatenate([eeg(2), eeg(0.6) + clench(0.6), eeg(2)], axis=1)
    fired = run(signal, threshold)
    assert len(fired) == 1 and 2.0 + MIN_CLENCH_S <= fired[0] <= 2.8


def test_short_twitch_does_not_fire():
    relaxed = [emg_rms(w, FS) for w in windows(eeg(10))]
    threshold = calibrate_threshold(relaxed, [emg_rms(w, FS) for w in windows(eeg(1) + clench(1))])
    signal = np.concatenate([eeg(2), eeg(0.15) + clench(0.15), eeg(2)], axis=1)
    assert run(signal, threshold) == []


def test_blink_sized_slow_wave_does_not_fire():
    relaxed = [emg_rms(w, FS) for w in windows(eeg(10))]
    threshold = calibrate_threshold(relaxed, [emg_rms(w, FS) for w in windows(eeg(1) + clench(1))])
    t = np.arange(int(1.0 * FS)) / FS
    blink = 300 * np.exp(-((t - 0.5) ** 2) / 0.01)  # big slow bump, like a blink (mostly < 10 Hz)
    assert run(eeg(1) + blink, threshold) == []


def test_holding_a_clench_fires_once_then_waits():
    relaxed = [emg_rms(w, FS) for w in windows(eeg(10))]
    threshold = calibrate_threshold(relaxed, [emg_rms(w, FS) for w in windows(eeg(1) + clench(1))])
    fired = run(eeg(3) + clench(3), threshold)  # clench held for 3 s
    assert len(fired) == 1  # one confirmation per clench; must relax before the next one


def test_two_separate_clenches_fire_twice_after_refractory():
    relaxed = [emg_rms(w, FS) for w in windows(eeg(10))]
    threshold = calibrate_threshold(relaxed, [emg_rms(w, FS) for w in windows(eeg(1) + clench(1))])
    gap = REFRACTORY_S + 0.5
    signal = np.concatenate([eeg(0.6) + clench(0.6), eeg(gap), eeg(0.6) + clench(0.6), eeg(1)], axis=1)
    assert len(run(signal, threshold)) == 2


def test_state_is_immutable():
    state = JawState()
    update_jaw(state, 999.0, 1.0, threshold=1.0)
    assert state.above_since is None
