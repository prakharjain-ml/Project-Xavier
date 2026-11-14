"""Jaw-clench confirmation detector (bci/jaw.py). Synthetic signals at the real board rate (1000 Hz)."""

import numpy as np
import pytest

from bci.jaw import (
    DEAD_RECOVERY_S,
    MIN_CLENCH_S,
    REFRACTORY_S,
    WINDOW_S,
    JawState,
    calibrate_threshold,
    dead_reason,
    emg_rms,
    mark_dead,
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


# ---- dead headset: a flat or railed signal must be refused and must never confirm (audit finding 9) ----

RAILED_CYTON_UV = -8388608 * (4.5 / 24 / (2 ** 23 - 1) * 1e6)  # a Cyton channel pinned at its limit: -187500.02 uV


def test_calibration_refuses_a_signal_with_no_energy_at_all():
    # Arrange: what a flat line gives in every window, relaxed and "clenched" alike
    relaxed, clenches = [0.0] * 100, [0.0] * 10

    # Act / Assert: the old check was `0 < 3 * 0`, which is False, so it accepted a threshold of 0
    with pytest.raises(ValueError, match="flat"):
        calibrate_threshold(relaxed, clenches)


def test_calibration_refuses_a_flat_relaxed_phase_even_if_noise_shows_up_later():
    with pytest.raises(ValueError, match="flat"):
        calibrate_threshold([1e-11] * 100, [2.0] * 10)  # 1e-11: float rounding on a constant, not a signal


def test_calibration_refuses_when_the_headset_sent_no_data():
    with pytest.raises(ValueError, match="no data"):
        calibrate_threshold([], [])


def test_calibration_refuses_values_that_are_not_numbers():
    with pytest.raises(ValueError, match="not a number"):
        calibrate_threshold([float("nan")] * 50, [float("nan")] * 10)


def test_calibrated_threshold_is_always_above_zero():
    relaxed = [emg_rms(w, FS) for w in windows(eeg(10))]
    clenches = [emg_rms(w, FS) for w in windows(eeg(1) + clench(1))]
    assert calibrate_threshold(relaxed, clenches) > 0


@pytest.mark.parametrize("threshold", [0.0, -1.0, float("nan")])
def test_a_threshold_that_is_not_above_zero_never_confirms(threshold):
    # Arrange
    state, fired = JawState(), []

    # Act: 2 s of windows, some flat (0.0) and some strong
    for i, rms in enumerate([0.0] * 10 + [500.0] * 10):
        state, hit = update_jaw(state, rms, (i + 1) * WINDOW_S, threshold)
        fired.append(hit)

    # Assert: a broken threshold must fail towards "no confirm", because a confirm starts a drive
    assert not any(fired)


def test_a_reading_that_is_not_a_number_never_confirms():
    state, fired = JawState(), []
    for i in range(20):
        state, hit = update_jaw(state, float("nan"), (i + 1) * WINDOW_S, threshold=10.0)
        fired.append(hit)
    assert not any(fired)


@pytest.mark.parametrize("fs", [250, 1000])
def test_dead_reason_names_flat_and_railed_windows_and_passes_a_live_one(fs):
    # Arrange
    n = int(WINDOW_S * fs)
    live = rng.normal(0, 15.0, (2, n))
    one_flat = np.vstack([live[0], np.zeros(n)])
    one_railed = np.vstack([np.full(n, RAILED_CYTON_UV), live[1]])
    clipping = live.copy()
    clipping[1, 3] = 187500.0  # a single sample at the positive limit is enough: the channel is saturating

    # Act / Assert
    assert dead_reason(live) is None
    assert "flat" in dead_reason(np.zeros((2, n)))
    assert "channel 2" in dead_reason(one_flat) and "flat" in dead_reason(one_flat)
    assert "channel 1" in dead_reason(one_railed) and "railed" in dead_reason(one_railed)
    assert "railed" in dead_reason(clipping)
    assert "invalid" in dead_reason(np.full((1, n), np.nan))


def test_a_dead_window_cancels_the_clench_in_progress_and_blocks_confirms_while_the_signal_recovers():
    # Arrange: two strong windows (0.2 s of a 0.3 s clench), then one dead window at t = 0.3 s
    state = JawState()
    for t in (0.1, 0.2):
        state, _ = update_jaw(state, 500.0, t, threshold=10.0)
    state = mark_dead(state, 0.3)

    # Act: the signal comes back already strong and stays strong (an electrode "pop" looks like this)
    fired = []
    for i in range(4, 40):
        state, hit = update_jaw(state, 500.0, i * WINDOW_S, threshold=10.0)
        fired.append(hit)

    # Assert: never confirmed, because the rider has not relaxed since the signal came back
    assert not any(fired)


def test_after_a_dead_window_a_real_clench_confirms_once_the_recovery_time_has_passed():
    # Arrange: dead at t = 1.0 s
    state = mark_dead(JawState(), 1.0)
    fired = []

    # Act: quiet for 0.2 s, then a clench held from 1.3 s to 3.0 s
    for i in range(11, 31):
        t = i * WINDOW_S
        state, hit = update_jaw(state, 1.0 if t < 1.25 else 500.0, t, threshold=10.0)
        if hit:
            fired.append(round(t, 1))

    # Assert: nothing during the recovery time, then exactly one confirm when it ends
    assert fired == [round(1.0 + DEAD_RECOVERY_S, 1)]
