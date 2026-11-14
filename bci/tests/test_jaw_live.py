"""Streaming wrapper around the jaw detector (bci/jaw_live.py): chunks of any size in, confirmations out."""

import sys
from pathlib import Path

import numpy as np
import pytest

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


def test_jaw_confirm_source_end_to_end_on_brainflow_fake_board():
    """Real BrainFlow synthetic board (no hardware) + scripted fake clenches through the real detector."""
    import time

    from bci.jaw_live import JawConfirmSource

    source = JawConfirmSource("synthetic", relax_s=1.5, clench_s=0.6, rest_s=0.3)
    try:
        source.calibrate(show=lambda _text: None)
        source.start()
        time.sleep(0.5)
        assert source.take() is False  # relaxed: no confirmation
        source.inject_fake_clench(0.8)
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline and not source.take():
            time.sleep(0.05)
        assert time.monotonic() < deadline  # the fake clench was confirmed
    finally:
        source.stop()


def test_parse_channels():
    import pytest

    from bci.jaw_live import parse_channels

    assert parse_channels("1") == (1,)
    assert parse_channels("1,2") == (1, 2)
    with pytest.raises(ValueError):
        parse_channels("9")


# ---- dead headset (audit finding 9) and a dead reader thread (finding 14) ----

RAILED_CYTON_UV = -8388608 * (4.5 / 24 / (2 ** 23 - 1) * 1e6)  # a Cyton channel pinned at its limit: -187500.02 uV
DEAD_SIGNALS = {
    "all zeros": lambda n: np.zeros((1, n)),
    "constant railed value": lambda n: np.full((1, n), RAILED_CYTON_UV),
}


def noise(fs, seconds, channels=1, uv=5.0, seed=1):
    return np.random.default_rng(seed).normal(0, uv, (channels, int(seconds * fs)))


def burst(fs, seconds, channels=1, uv=120.0, seed=2):
    """A strong broadband burst (a stand-in for a clench) that works at 250 Hz as well as 1000 Hz."""
    return np.random.default_rng(seed).normal(0, uv, (channels, int(seconds * fs)))


def calibrated_stream(fs, channels=1):
    stream = JawStream(fs)
    stream.collect("relaxed", noise(fs, 10, channels))
    for i in range(3):
        stream.collect("clench", burst(fs, 1, channels, seed=10 + i))
    stream.finish_calibration()
    return stream


@pytest.mark.parametrize("fs", [250, 1000])
@pytest.mark.parametrize("name", list(DEAD_SIGNALS))
def test_calibration_refuses_a_dead_headset(fs, name):
    # Arrange: the same dead signal in the relaxed phase and in all three "clenches"
    make, stream = DEAD_SIGNALS[name], JawStream(fs)
    stream.collect("relaxed", make(10 * fs))
    for _ in range(3):
        stream.collect("clench", make(fs))

    # Act / Assert: refused with a message a person can act on, and no threshold is left behind
    with pytest.raises(ValueError, match="flat|railed"):
        stream.finish_calibration()
    assert stream.threshold is None
    assert stream.push(make(20 * fs)) == []  # and so the same dead signal can never confirm


@pytest.mark.parametrize("fs", [250, 1000])
def test_calibration_refuses_when_the_channel_was_railed_while_relaxed_and_only_noise_came_after(fs):
    stream = JawStream(fs)
    stream.collect("relaxed", np.full((1, 10 * fs), RAILED_CYTON_UV))
    for i in range(3):
        stream.collect("clench", noise(fs, 1, seed=i))  # 5 uV noise, nobody clenching
    with pytest.raises(ValueError, match="railed"):
        stream.finish_calibration()


def test_calibration_refuses_when_one_of_two_channels_is_railed():
    # Arrange: channel 1 is fine and shows clear clenches; channel 2 sits at the amplifier limit
    fs, stream = 250, JawStream(250)
    stream.collect("relaxed", np.vstack([noise(fs, 10), np.full((1, 10 * fs), RAILED_CYTON_UV)]))
    for i in range(3):
        stream.collect("clench", np.vstack([burst(fs, 1, seed=i), np.full((1, fs), RAILED_CYTON_UV)]))

    # Act / Assert: a railed channel that starts flapping later would look like a clench, so name it and refuse
    with pytest.raises(ValueError, match="channel 2.*railed"):
        stream.finish_calibration()


@pytest.mark.parametrize("fs", [250, 1000])
@pytest.mark.parametrize("name", list(DEAD_SIGNALS))
def test_signal_that_goes_dead_after_a_good_calibration_never_confirms(fs, name):
    # Arrange
    stream = calibrated_stream(fs)
    assert len(feed(stream, np.concatenate([noise(fs, 1), burst(fs, 0.6), noise(fs, 1)], axis=1), 37)) == 1

    # Act: the headset dies (20 s), comes back with only noise, dies again
    signal = np.concatenate([DEAD_SIGNALS[name](20 * fs), noise(fs, 2), DEAD_SIGNALS[name](5 * fs)], axis=1)
    fired = feed(stream, signal, chunk=37)

    # Assert: no confirm, and the stream says what is wrong so the caller can show it
    assert fired == []
    assert stream.signal_problem is not None and ("flat" in stream.signal_problem or "railed" in stream.signal_problem)


@pytest.mark.parametrize("fs", [250, 1000])
def test_loose_electrode_flapping_between_the_rail_and_the_scalp_never_confirms(fs):
    # Arrange: every 30 ms the channel jumps between the amplifier limit and normal noise. Each jump is a
    # huge broadband step, far above the threshold, for 3 s: without the dead-window check this "clenches".
    stream = calibrated_stream(fs)
    signal = noise(fs, 3, seed=3)
    block = int(0.03 * fs)
    for start in range(0, signal.shape[1], 2 * block):
        signal[:, start:start + block] = RAILED_CYTON_UV

    # Act
    fired = feed(stream, signal, chunk=37)

    # Assert
    assert fired == []


def test_real_clench_still_confirms_after_the_signal_has_recovered_from_a_dead_spell():
    # Arrange
    fs = 250
    stream = calibrated_stream(fs)
    signal = np.concatenate([np.zeros((1, 2 * fs)), noise(fs, 2), burst(fs, 0.6), noise(fs, 1)], axis=1)

    # Act
    fired = feed(stream, signal, chunk=37)

    # Assert: refusing a dead signal must not leave the detector stuck
    assert len(fired) == 1


class FakeBoard:
    """Stands in for BrainFlow's board: hands out chunks, then raises like an unplugged board does."""

    def __init__(self, fs, make_chunk, fail_after_reads=None):
        self.fs, self.make_chunk, self.fail_after_reads, self.reads = fs, make_chunk, fail_after_reads, 0

    def get_board_data(self):
        self.reads += 1
        if self.fail_after_reads is not None and self.reads > self.fail_after_reads:
            raise RuntimeError("BOARD_NOT_READY_ERROR: board unplugged")
        return self.make_chunk(int(0.05 * self.fs))

    def stop_stream(self):
        pass

    def release_session(self):
        pass


def fake_source(monkeypatch, board, **kwargs):
    import bci.jaw_live as jaw_live

    monkeypatch.setattr(jaw_live, "connect_board", lambda mode, port, channels: (board, [0], board.fs))
    return jaw_live.JawConfirmSource("dongle", "/dev/null-not-opened", **kwargs)


def wait_until(condition, timeout_s=5.0):
    """Poll instead of sleeping a fixed time, so a loaded machine only makes the test slower, not flaky."""
    import time

    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.01)
    return condition()


def test_jaw_source_calibration_fails_clearly_on_a_board_that_streams_a_flat_line(monkeypatch):
    # Arrange
    source = fake_source(monkeypatch, FakeBoard(250, lambda n: np.zeros((1, n))), relax_s=0.3, clench_s=0.2, rest_s=0.0)

    # Act / Assert
    try:
        with pytest.raises(ValueError, match="flat"):
            source.calibrate(show=lambda _text: None)
    finally:
        source.stop()


def test_jaw_source_reports_alive_while_its_reader_thread_is_healthy(monkeypatch):
    # Arrange
    board = FakeBoard(250, lambda n: np.random.default_rng().normal(0, 5.0, (1, n)))
    source = fake_source(monkeypatch, board)

    # Act
    source.start()
    try:
        read_a_few_times = wait_until(lambda: board.reads >= 3)

        # Assert
        assert read_a_few_times and source.alive() and source.error is None
    finally:
        source.stop()


def test_jaw_source_reader_thread_death_is_logged_and_visible_to_the_caller(monkeypatch, caplog):
    # Arrange: the board raises on its third read, as BrainFlow does when the dongle is pulled out
    import logging

    board = FakeBoard(250, lambda n: np.random.default_rng().normal(0, 5.0, (1, n)), fail_after_reads=2)
    source = fake_source(monkeypatch, board)

    # Act
    with caplog.at_level(logging.ERROR, logger="bci.jaw_live"):
        source.start()
        try:
            died = wait_until(lambda: not source.alive())
        finally:
            source.stop()

    # Assert: the caller can see it, the log says why, and a dead source never confirms
    assert died and not source.alive()
    assert isinstance(source.error, RuntimeError) and "unplugged" in str(source.error)
    assert any("unplugged" in record.getMessage() or (record.exc_info and "unplugged" in str(record.exc_info[1]))
               for record in caplog.records)
    assert source.take() is False


def test_jaw_source_warns_and_never_confirms_when_the_live_signal_goes_flat(monkeypatch, caplog):
    # Arrange: a board that gives noise, strong bursts while the screen says CLENCH, and later a flat line
    import logging

    mode = {"now": "noise"}
    chunks = {
        "noise": lambda n: np.random.default_rng().normal(0, 5.0, (1, n)),
        "burst": lambda n: np.random.default_rng().normal(0, 120.0, (1, n)),
        "flat": lambda n: np.zeros((1, n)),
    }
    board = FakeBoard(250, lambda n: chunks[mode["now"]](n))
    source = fake_source(monkeypatch, board, relax_s=1.0, clench_s=0.5, rest_s=0.1)

    def show(text):
        mode["now"] = "burst" if "CLENCH" in text else "noise"

    source.calibrate(show)
    mode["now"] = "flat"

    # Act
    with caplog.at_level(logging.WARNING, logger="bci.jaw_live"):
        source.start()
        try:
            warned = wait_until(lambda: any("flat" in record.getMessage() for record in caplog.records))
            confirmed = source.take()
        finally:
            source.stop()

    # Assert: the problem is in the log, the thread is still alive (a flat signal is not a crash), no confirm
    assert warned and source.alive() and confirmed is False
