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
   clearly stronger (bad electrode contact) or if the signal has no energy at all (headset off or unplugged).
4. dead_reason() / mark_dead(): a window that is flat or pinned at the amplifier limit ("railed") is not a
   measurement. Calibration refuses it, and live it cancels the clench in progress. A confirm starts a drive,
   so every doubt here ends in "no confirm".
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
# A flat line has no muscle-band energy at all: exactly 0, or about 1e-10 from float rounding when the constant
# is large. A working amplifier is never that quiet (the Cyton's own noise is about 0.1 uV), so anything below
# this floor is a dead input, not a very relaxed jaw.
MIN_LIVE_RMS_UV = 0.01
# The Cyton cannot measure beyond +-187 500 uV (4.5 V reference / gain 24). A channel whose electrode, reference
# or bias clip is off drifts there and stays ("railed"). A sample this close to the limit is the limit.
RAILED_UV = 187_000.0
# When a dead channel comes back, the amplifier settles with a "pop" that has energy at every frequency, just
# like a clench. Ignore the signal for this long after the newest dead window.
DEAD_RECOVERY_S = 1.0
# A window this many times stronger than the rider's own calibrated clench is not muscle: it is an electrode
# coming loose or being touched. Measured Sat Nov 14 on Prakhar (temples, Wi-Fi shield, 1000 Hz): relaxed 6.7 uV,
# clench 97 uV, strongest clench window 120 uV (1.2x), electrode knocked loose 400 to 2300 uV (4x to 24x). Without
# this limit that loose electrode produced 4 false confirms in 11 s.
ARTIFACT_RATIO = 4.0


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


def dead_reason(window: np.ndarray) -> str | None:
    """Why one window (channels x samples, RAW microvolts, before any filtering) cannot be trusted, else None.

    Checked per channel, because emg_rms() reports the largest channel: one bad channel is enough to fake a
    clench. "Channel 1" is the first of the channels in use (the first number given to --channels).
    """
    x = np.atleast_2d(np.asarray(window, dtype=float))
    for number, samples in enumerate(x, start=1):
        if not np.all(np.isfinite(samples)):
            return f"channel {number} has invalid samples (not numbers)"
        if np.max(np.abs(samples)) >= RAILED_UV:  # even one sample at the limit: the amplifier is saturating
            return f"channel {number} is railed (pinned at the amplifier limit: electrode or ear clip not connected)"
        if np.ptp(samples) == 0:  # every sample identical; real skin and a real amplifier always add some noise
            return f"channel {number} is flat (no signal: headset off, unplugged or not streaming)"
    return None


def calibrate_threshold(relaxed: Sequence[float], clenches: Sequence[float]) -> float:
    """Threshold between the relaxed level (95th percentile) and a typical clench (median), on a log scale.

    Raises ValueError when the data cannot give a threshold worth trusting. The result is always above zero.
    """
    if len(relaxed) == 0 or len(clenches) == 0:
        raise ValueError("no data from the headset during calibration: check that it is on and streaming")
    if not (np.all(np.isfinite(relaxed)) and np.all(np.isfinite(clenches))):
        raise ValueError("calibration signal is not a number (NaN or infinite): check the headset connection")
    relaxed_typical, relaxed_high = float(np.median(relaxed)), float(np.percentile(relaxed, 95))
    clench_typical = float(np.median(clenches))
    # Without this floor a dead headset passes: relaxed = 0 makes the ratio test below `0 < 3 * 0`, which is
    # False, and the threshold becomes 0, which every later window "exceeds".
    if relaxed_typical < MIN_LIVE_RMS_UV:
        raise ValueError(f"relaxed signal is flat ({relaxed_typical:.2g} uV in the muscle band): the headset looks "
                         "off, unplugged or railed; check power, the dongle and every electrode")
    if clench_typical < MIN_RATIO * relaxed_typical:
        raise ValueError(f"clench only {clench_typical / relaxed_typical:.1f}x relaxed (need {MIN_RATIO:.0f}x): "
                         "check electrode contact and clench harder")
    return float(np.sqrt(relaxed_high * clench_typical))  # geometric mean: halfway on a log scale


@dataclass(frozen=True)
class JawState:
    above_since: float | None = None  # start of the current above-threshold stretch
    last_fire: float | None = None
    armed: bool = True  # False after a fire until the rider relaxes (one confirmation per clench)
    dead_at: float | None = None  # end time of the newest flat or railed window (see mark_dead)


def mark_dead(state: JawState, t: float) -> JawState:
    """Call instead of update_jaw() for a window where dead_reason() is not None (t = window end time).

    It forgets the clench in progress, starts the DEAD_RECOVERY_S wait, and disarms: after the signal returns
    the rider must be seen relaxed once before a clench can count. So a loose electrode that keeps jumping
    to the rail and back, however violently, never adds up to a confirm.
    """
    return replace(state, above_since=None, armed=False, dead_at=t)


def update_jaw(state: JawState, rms: float, t: float, threshold: float) -> tuple[JawState, bool]:
    """Feed one window's emg_rms (t = window end time). Returns (new state, True if a clench was confirmed)."""
    # Written as "not (... >=)" on purpose: a NaN reading or a NaN / zero / negative threshold makes the
    # comparison False, so anything broken counts as "relaxed" and cannot confirm.
    if not (threshold > 0 and rms >= threshold):
        return replace(state, above_since=None, armed=True), False
    since = state.above_since if state.above_since is not None else t - WINDOW_S
    long_enough = t - since >= MIN_CLENCH_S - 1e-9
    rested = state.last_fire is None or t - state.last_fire >= REFRACTORY_S
    recovered = state.dead_at is None or t - state.dead_at >= DEAD_RECOVERY_S - 1e-9
    if long_enough and state.armed and rested and recovered:
        return replace(state, above_since=since, last_fire=t, armed=False), True
    return replace(state, above_since=since), False
