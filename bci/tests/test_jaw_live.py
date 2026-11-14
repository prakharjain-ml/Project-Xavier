"""Streaming wrapper around the jaw detector (bci/jaw_live.py): chunks of any size in, confirmations out."""

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from test_jaw import FS, clench, eeg  # noqa: E402  (reuse the synthetic signals)

from bci.jaw_live import JawStream  # noqa: E402


def feed(stream, signal, chunk):
    fired = []
    for i in range(0, signal.shape[1], chunk):
        fired += stream.push(signal[:, i:i + chunk])
    return fired


def test_calibrate_then_detect_with_uneven_chunks():
    stream = JawStream(FS)
    stream.collect("relaxed", eeg(10))
    for _ in range(3):
        stream.collect("clench", eeg(1) + clench(1))
    stream.finish_calibration()
    signal = np.concatenate([eeg(2), eeg(0.6) + clench(0.6), eeg(2), eeg(0.6) + clench(0.6), eeg(1)], axis=1)
    fired = feed(stream, signal, chunk=37)  # board packets never line up with 0.1 s windows
    assert len(fired) == 2


def test_no_confirmations_before_calibration():
    stream = JawStream(FS)
    assert feed(stream, eeg(1) + clench(1), chunk=100) == []


def test_bad_contact_fails_calibration_clearly():
    stream = JawStream(FS)
    stream.collect("relaxed", eeg(5))
    stream.collect("clench", eeg(2))  # rider "clenched" but nothing showed up
    try:
        stream.finish_calibration()
        raise AssertionError("calibration should have failed")
    except ValueError as error:
        assert "clench" in str(error)
