"""Jaw-clench confirmation from the OpenBCI headset.

A jaw clench is a MUSCLE signal (EMG), not a brain signal: the jaw muscles put a strong, fast buzz (roughly
40-200 Hz) on every scalp electrode, far larger than EEG. That makes it a dependable "yes, confirm" even when
the EEG itself is weak. Say so honestly in the pitch.

Pipeline, every WINDOW_S (0.1 s) of samples from each channel:
1. emg_rms(): energy in 40-200 Hz, skipping the 60/120/180 Hz mains-hum bins (our board shows huge 60 Hz hum).
2. update_jaw(): fire once when that energy stays above a per-person threshold for MIN_CLENCH_S (0.3 s), so
   twitches, blinks (slow, < 20 Hz) and speech bursts do not confirm. One fire per clench: the rider must
   relax before the next one, and REFRACTORY_S must pass.
3. calibrate_threshold(): 10 s relaxed + 3 clenches -> threshold between the two; refuses if a clench is not
   clearly stronger (bad electrode contact), so a broken headset can never confirm anything.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace

import numpy as np

WINDOW_S = 0.1
MIN_CLENCH_S = 0.3
REFRACTORY_S = 1.0
EMG_BAND_HZ = (40.0, 200.0)
MAINS_HZ = (60.0, 120.0, 180.0)
MAINS_GUARD_HZ = 12.0  # 0.1 s windows have 10 Hz bins and hum leaks into the neighbours: skip +-12 Hz
MIN_RATIO = 3.0  # a clench must be at least 3x the relaxed level, or calibration fails


def emg_rms(window: np.ndarray, fs: float) -> float:
    """Muscle-band energy of one window (channels x samples, microvolts): the largest channel's value.

    Computed with an FFT rather than a filter: a 0.1 s window is too short for a band-pass filter to settle,
    and its start-up ringing would look like a clench.
    """
    x = np.atleast_2d(np.asarray(window, dtype=float))
    x = x - x.mean(axis=1, keepdims=True)
    taper = np.hanning(x.shape[1])
    spectrum = np.abs(np.fft.rfft(x * taper, axis=1)) ** 2
    freqs = np.fft.rfftfreq(x.shape[1], 1.0 / fs)
    keep = (freqs >= EMG_BAND_HZ[0]) & (freqs <= EMG_BAND_HZ[1])
    for hum in MAINS_HZ:
        keep &= np.abs(freqs - hum) > MAINS_GUARD_HZ
    power = spectrum[:, keep].sum(axis=1) / (np.sum(taper ** 2) * x.shape[1])
    return float(np.sqrt(power.max()))


def calibrate_threshold(relaxed: Sequence[float], clenches: Sequence[float]) -> float:
    """Threshold between the relaxed level (95th percentile) and a typical clench (median), on a log scale."""
    relaxed_typical, relaxed_high = float(np.median(relaxed)), float(np.percentile(relaxed, 95))
    clench_typical = float(np.median(clenches))
    if clench_typical < MIN_RATIO * relaxed_typical:
        raise ValueError(f"clench only {clench_typical / relaxed_typical:.1f}x relaxed (need {MIN_RATIO:.0f}x): "
                         "check electrode contact and clench harder")
    return float(np.sqrt(relaxed_high * clench_typical))  # geometric mean: halfway on a log scale


@dataclass(frozen=True)
class JawState:
    above_since: float | None = None  # start of the current above-threshold stretch
    last_fire: float | None = None
    armed: bool = True  # False after a fire until the rider relaxes (one confirmation per clench)


def update_jaw(state: JawState, rms: float, t: float, threshold: float) -> tuple[JawState, bool]:
    """Feed one window's emg_rms (t = window end time). Returns (new state, True if a clench was confirmed)."""
    if rms < threshold:
        return replace(state, above_since=None, armed=True), False
    since = state.above_since if state.above_since is not None else t - WINDOW_S
    long_enough = t - since >= MIN_CLENCH_S - 1e-9
    rested = state.last_fire is None or t - state.last_fire >= REFRACTORY_S
    if long_enough and state.armed and rested:
        return JawState(above_since=since, last_fire=t, armed=False), True
    return replace(state, above_since=since), False
