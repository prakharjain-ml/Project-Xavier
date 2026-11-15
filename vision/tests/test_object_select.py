"""Gaze-on-objects selection logic (vision/object_select.py). Pure: no camera, no window."""

import inspect
import logging
import math
import queue
import time
import types

import numpy as np
import pytest

from motors.mock_serial import MockSerial
from shared.protocol import DWELL_S, STALE_INTENT_S
from vision.detect_track import Track
from vision.gaze import GazeSample
from vision.object_select import (
    MIN_HIT_SIZE,
    MIN_LOOK_S,
    Selection,
    corrected_point,
    hit_boxes,
    update_selection,
)


def track(tid, bbox):
    return Track(id=tid, label="chair", conf=0.9, bbox=bbox, distance_m=2.0)


def test_dwell_on_one_object_confirms_it():
    sel = update_selection(Selection(), hit=7, now=0.0)
    assert (sel.candidate, sel.confirmed) == (7, None)
    sel = update_selection(sel, hit=7, now=DWELL_S - 0.1)
    assert sel.confirmed is None  # not yet
    sel = update_selection(sel, hit=7, now=DWELL_S + 0.01)
    assert sel.confirmed == 7


def test_looking_away_resets_the_dwell_but_keeps_a_confirmation():
    sel = update_selection(Selection(), hit=7, now=0.0)
    sel = update_selection(sel, hit=None, now=1.0)
    assert sel.candidate is None
    sel = update_selection(sel, hit=7, now=1.1)
    sel = update_selection(sel, hit=7, now=1.1 + DWELL_S - 0.1)
    assert sel.confirmed is None  # the earlier 1 s did not count: dwell restarted
    sel = update_selection(sel, hit=7, now=1.1 + DWELL_S + 0.01)
    sel = update_selection(sel, hit=None, now=5.0)
    assert sel.confirmed == 7  # looking away does not undo a confirmation (cancel key does)


def test_switching_objects_needs_a_full_new_dwell():
    sel = Selection(candidate=7, since=0.0, confirmed=7)
    sel = update_selection(sel, hit=9, now=10.0)
    assert sel.confirmed == 7 and sel.candidate == 9
    sel = update_selection(sel, hit=9, now=10.0 + DWELL_S + 0.01)
    assert sel.confirmed == 9


def test_selection_is_immutable():
    sel = Selection()
    update_selection(sel, hit=3, now=0.0)
    assert sel.candidate is None


def test_hit_boxes_are_normalized_and_small_objects_get_a_minimum_size():
    targets = [track(1, (0, 0, 960, 540)), track(2, (1800, 1000, 1810, 1010))]  # big box, tiny box
    boxes = hit_boxes(targets, frame_w=1920, frame_h=1080)
    assert boxes[1] == pytest.approx((0.0, 0.0, 0.5, 0.5))
    x1, y1, x2, y2 = boxes[2]
    assert x2 - x1 == pytest.approx(MIN_HIT_SIZE) and y2 - y1 == pytest.approx(MIN_HIT_SIZE)
    assert 0.0 <= x1 and x2 <= 1.0 and 0.0 <= y1 and y2 <= 1.0  # enlarged box stays on screen


def test_corrected_point_applies_offset_and_rejects_stale_or_missing():
    sample = GazeSample((0.4, 0.7), False, True, 10.0)
    assert corrected_point(sample, offset=(0.1, -0.2), now=10.1) == pytest.approx((0.5, 0.5))
    assert corrected_point(sample, offset=(0.0, 0.0), now=11.0) is None  # older than 0.5 s
    assert corrected_point(GazeSample(None, True, True, 10.0), offset=(0.0, 0.0), now=10.0) is None
    assert corrected_point(None, offset=(0.0, 0.0), now=10.0) is None


def test_dwell_carries_over_when_the_tracker_relabels_the_same_object():
    box = (0.1, 0.1, 0.4, 0.5)
    sel = update_selection(Selection(), hit=84, now=0.0, box=box)
    nudged = (0.11, 0.1, 0.41, 0.5)  # same chair, new ID from the tracker
    sel = update_selection(sel, hit=130, now=1.0, box=nudged)
    assert sel.candidate == 130 and sel.since == 0.0  # dwell kept running
    sel = update_selection(sel, hit=130, now=DWELL_S + 0.01, box=nudged)
    assert sel.confirmed == 130


def test_a_different_object_elsewhere_still_restarts_the_dwell():
    sel = update_selection(Selection(), hit=84, now=0.0, box=(0.1, 0.1, 0.4, 0.5))
    sel = update_selection(sel, hit=130, now=1.0, box=(0.6, 0.1, 0.9, 0.5))  # no overlap: really another object
    assert sel.since == 1.0


def test_gaze_problem_names_the_reason():
    from vision.object_select import gaze_problem

    assert gaze_problem(None, now=1.0) == "no_sample"
    assert gaze_problem(GazeSample((0.5, 0.5), False, True, 0.0), now=5.0) == "stale"
    assert gaze_problem(GazeSample(None, False, False, 1.0), now=1.0) == "no_face"
    assert gaze_problem(GazeSample(None, True, True, 1.0), now=1.0) == "eyes_closed"
    assert gaze_problem(GazeSample((0.5, 0.5), False, True, 1.0), now=1.0) is None


def test_session_ends_at_once_if_the_eye_tracker_dies():
    import queue
    import time

    from vision.object_select import run

    class FakeCv2:
        def waitKey(self, _ms):  # noqa: N802 - OpenCV's name
            return 255

        def imshow(self, *_args):
            pass

    class NoFrames:
        def latest(self):
            return None

    start = time.monotonic()
    result = run(FakeCv2(), NoFrames(), model=None, classes=None, gaze_queue=queue.Queue(), hfov=70.0,
                 device="cpu", seconds=5.0, tracker_alive=lambda: False)
    assert result == [] and time.monotonic() - start < 1.0  # did not sit there for the full 5 s


def test_confirm_event_needs_a_short_look_first():
    from vision.object_select import MIN_LOOK_S

    sel = update_selection(Selection(), hit=7, now=0.0, dwell_s=None)
    sel = update_selection(sel, hit=7, now=MIN_LOOK_S / 2, dwell_s=None, confirm=True)
    assert sel.confirmed is None  # clench while the eyes are still arriving: ignored
    sel = update_selection(sel, hit=7, now=MIN_LOOK_S + 0.01, dwell_s=None, confirm=True)
    assert sel.confirmed == 7


def test_confirm_mode_never_confirms_by_dwell_alone():
    sel = update_selection(Selection(), hit=7, now=0.0, dwell_s=None)
    sel = update_selection(sel, hit=7, now=10.0, dwell_s=None)
    assert sel.confirmed is None  # looking for 10 s without a clench does nothing


def test_confirm_event_with_nothing_under_the_gaze_does_nothing():
    sel = update_selection(Selection(), hit=None, now=1.0, dwell_s=None, confirm=True)
    assert sel.confirmed is None


def test_confirm_settings_per_mode():
    from vision.object_select import confirm_settings

    assert confirm_settings("dwell") == DWELL_S  # dwell confirms by itself
    assert confirm_settings("key") is None and confirm_settings("jaw") is None  # only a deliberate action confirms


def test_confirm_event_sources():
    from vision.object_select import confirm_event

    class FakeJaw:
        mode = "dongle"

        def __init__(self, fired):
            self.fired, self.injected = fired, False

        def take(self):
            return self.fired

        def alive(self):
            return True

        def inject_fake_clench(self, seconds=0.6):
            self.injected = True

    assert confirm_event("dwell", ord("j"), None) is False
    assert confirm_event("key", ord("j"), None) is True and confirm_event("key", ord("x"), None) is False
    assert confirm_event("jaw", 255, FakeJaw(True)) is True
    jaw = FakeJaw(False)
    assert confirm_event("jaw", ord("j"), jaw) is False and not jaw.injected  # real board: J does nothing
    practice = FakeJaw(False)
    practice.mode = "synthetic"
    confirm_event("jaw", ord("j"), practice)
    assert practice.injected  # practice board: J injects a fake clench into the real detector


def test_drive_intent_only_while_looking_at_the_confirmed_visible_target():
    from shared.protocol import Target as T
    from vision.object_select import drive_intent

    targets = [track(4, (900, 300, 1100, 700))]
    sel = Selection(candidate=4, since=0.0, confirmed=4)
    assert drive_intent(sel, hit=4, targets=targets) == T.FWD
    assert drive_intent(sel, hit=None, targets=targets) == T.NONE  # looked away: hold-to-move says stop
    assert drive_intent(sel, hit=4, targets=[]) == T.NONE  # target lost from view: stop
    assert drive_intent(Selection(candidate=4, since=0.0), hit=4, targets=targets) == T.NONE  # not confirmed yet


def test_end_to_end_look_confirm_hold_then_drive_lines_reach_the_port(monkeypatch):
    """Real selection + planner + state machine + driver into MockSerial; only camera, YOLO and gaze are faked."""
    import queue
    import time
    import types

    import cv2 as real_cv2
    import numpy as np

    import vision.object_select as osel
    from motors.driver import MotorDriver
    from motors.mock_serial import MockSerial

    chair = Track(id=4, label="chair", conf=0.9, bbox=(860, 300, 1060, 800), distance_m=2.5)
    monkeypatch.setattr(osel, "detect", lambda *a, **k: [chair])

    class Frames:
        def latest(self):
            return np.zeros((1080, 1920, 3), np.uint8), time.monotonic()

    class GazeAtChair:  # looks at the chair's centre the whole time
        def __init__(self):
            self.flip = False

        def get_nowait(self):
            self.flip = not self.flip
            if self.flip:
                return GazeSample((0.5, 0.5), False, True, time.monotonic())
            raise queue.Empty

    calls = {"n": 0, "j_at": None}

    def wait_key(_ms):
        calls["n"] += 1
        time.sleep(0.01)
        if calls["n"] == 60:  # press J (confirm) after ~0.6 s of looking
            calls["j_at"] = time.monotonic()
            return ord("j")
        if sum(ln.startswith("C,") for ln in port.lines()) >= 5:
            return ord("q")  # seen enough driving: quit, so a slow (loaded) machine only makes the test longer
        return 255

    fake_cv2 = types.SimpleNamespace(**{n: getattr(real_cv2, n) for n in dir(real_cv2) if not n.startswith("_")})
    fake_cv2.imshow, fake_cv2.waitKey = (lambda *a: None), wait_key
    class TimedPort(MockSerial):
        def __init__(self):
            super().__init__()
            self.times = []

        def write(self, data):
            self.times.append(time.monotonic())
            return super().write(data)

    port = TimedPort()
    driver = MotorDriver(lambda: port)
    driver.start()
    try:
        confirmations = osel.run(fake_cv2, Frames(), model=None, classes=None, gaze_queue=GazeAtChair(), hfov=85.5,
                                 device="cpu", seconds=15.0, confirm_mode="key", driver=driver)
    finally:
        driver.stop()
    assert any("CONFIRMED chair #4" in c for c in confirmations)
    drive = [ln for ln in port.lines() if ln.startswith("C,")]
    assert drive, "no drive lines reached the port"
    left, right = map(int, drive[-1].split(",")[2:])
    assert left > 0 and right > 0  # driving toward the centred chair
    first_drive = next(i for i, ln in enumerate(port.lines()) if ln.startswith("C,"))
    from shared.protocol import DWELL_S as HOLD

    # The safety state machine is in the path: wheels move only after the 1.5 s hold that follows the confirm.
    assert port.times[first_drive] - calls["j_at"] >= HOLD - 0.15
    assert all(ln.startswith("S,") for ln in port.lines()[-3:])  # explicit stop when the session ends


# ---------------------------------------------------------------------------------------------------------------
# Drive path (`object_select --drive`): regression tests for the safety audit, docs/PROJECT_CONTEXT.md findings
# 1 (frozen camera), 3 (operator keys), 6 (obstacles the planner never saw) and 14 (arrival repeated forever).
#
# Same recipe as the end-to-end test above: the real selection, planner, safety state machine and MotorDriver
# write into MockSerial; only the camera, YOLO, the eye tracker and the OpenCV window are faked.
# Each test is a SCRIPT of events ("once the wheels turn, press SPACE"), not a list of fixed times, and it quits
# by itself as soon as it has seen enough. A slow, loaded machine only makes a test take longer.

NO_KEY, SPACE, QUIT = 255, 32, ord("q")
CENTRE, EMPTY_CORNER = (0.5, 0.5), (0.05, 0.05)  # gaze points (0-1 screen): on the chair / on nothing
CHAIR = Track(id=4, label="chair", conf=0.9, bbox=(860, 300, 1060, 800), distance_m=2.5)  # dead ahead, far away
FRAME_W, FRAME_H = 1920, 1080
LOOP_S = 0.01  # the fake waitKey sleeps this long, so the loop runs at most 100 times a second
WAIT_CAP_S = 15.0  # a scripted step that has not happened after this long fails the test with a clear message
# A stop decided in the loop reaches the port on the driver's next tick (50 ms). Allow ten ticks on a loaded machine.
SETTLE_S = 0.5


class TimedPort(MockSerial):
    """MockSerial that also remembers when each line was written (the driver thread is the only writer)."""

    def __init__(self) -> None:
        super().__init__()
        self.times: list[float] = []

    def write(self, data: bytes) -> int:
        written = super().write(data)
        self.times.append(time.monotonic())
        return written


class DriveSession:
    """One scripted drive session. It IS the fake forward camera (latest) and the fake eye tracker (get_nowait),
    and it records what a test may look at: the serial port, the status text on screen and the log."""

    def __init__(self) -> None:
        self.port = TimedPort()
        self.gaze_point: tuple[float, float] | None = CENTRE  # where the rider looks right now
        self.camera_live = True
        self.frozen_frame_t: float | None = None  # timestamp of the last frame before the camera froze
        self.statuses: list[tuple[float, str]] = []  # (time, status text handed to draw())
        self.log: list[str] = []  # messages logged by vision.object_select
        self.marks: dict[str, float] = {}  # named moments set by the script
        self.confirmations: list[str] = []  # what run() returned
        self._frame = (np.zeros((FRAME_H, FRAME_W, 3), np.uint8), time.monotonic())
        self._gaze_flip = False

    # ---- fakes the program reads from
    def latest(self) -> tuple[np.ndarray, float]:
        """Like LatestFrameReader.latest(): a live camera gives a new arrival time every call; a frozen one keeps
        returning the last frame with its OLD arrival time."""
        if self.camera_live:
            self._frame = (self._frame[0], time.monotonic())
        return self._frame

    def get_nowait(self) -> GazeSample:
        """A fresh gaze sample on every other call (the caller drains the queue until it is empty)."""
        self._gaze_flip = not self._gaze_flip
        if not self._gaze_flip:
            raise queue.Empty
        return GazeSample(self.gaze_point, False, self.gaze_point is not None, time.monotonic())

    # ---- what a script can do
    def freeze_camera(self) -> None:
        self.camera_live, self.frozen_frame_t = False, self._frame[1]

    def mark(self, name: str) -> None:
        self.marks[name] = time.monotonic()

    def wait(self, seconds: float):
        """Script step: press nothing for this long."""
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            yield NO_KEY

    def until(self, condition, what: str, key: int = NO_KEY):
        """Script step: press `key` (default: nothing) once per loop pass until condition() is true."""
        deadline = time.monotonic() + WAIT_CAP_S
        while not condition():
            assert time.monotonic() < deadline, f"gave up after {WAIT_CAP_S:.0f} s waiting for: {what}"
            yield key

    # ---- what a script or a test can see
    def moving_lines(self, after: float = -math.inf, before: float = math.inf) -> list[str]:
        """Serial lines that turn the wheels ("C,seq,left,right"; zero speeds are always sent as "S,seq")."""
        return [line for t, line in zip(self.port.times, self.port.lines())
                if line.startswith("C,") and after < t < before]

    def is_moving(self) -> bool:
        return bool(self.moving_lines())

    def logged(self, word: str) -> int:
        return sum(word in message for message in self.log)


def run_drive_session(monkeypatch, tracks: list[Track], script, confirm_mode: str = "key",
                      **run_options) -> DriveSession:
    """Run the real osel.run() with a MotorDriver on MockSerial. `script(session)` is a generator: every value it
    yields is the key pressed in one loop pass; when it ends, Q is pressed and the session closes."""
    import cv2 as real_cv2

    import vision.object_select as osel
    from motors.driver import MotorDriver

    session = DriveSession()
    monkeypatch.setattr(osel, "detect", lambda *a, **k: list(tracks))
    real_draw = osel.draw

    def draw_and_note_status(*args, **kwargs):  # found by parameter name, so draw() may gain parameters
        status = inspect.signature(real_draw).bind(*args, **kwargs).arguments["status"]
        session.statuses.append((time.monotonic(), status))
        return real_draw(*args, **kwargs)

    monkeypatch.setattr(osel, "draw", draw_and_note_status)
    keys = script(session)

    def wait_key(_ms: int) -> int:
        time.sleep(LOOP_S)
        return next(keys, QUIT)

    fake_cv2 = types.SimpleNamespace(**{n: getattr(real_cv2, n) for n in dir(real_cv2) if not n.startswith("_")})
    fake_cv2.imshow, fake_cv2.waitKey = (lambda *a: None), wait_key

    class Remember(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            session.log.append(record.getMessage())

    handler, old_level = Remember(), osel.log.level
    osel.log.addHandler(handler)
    osel.log.setLevel(logging.INFO)
    driver = MotorDriver(lambda: session.port)
    driver.start()
    try:
        session.confirmations = osel.run(fake_cv2, session, model=None, classes=None, gaze_queue=session,
                                         hfov=85.5, device="cpu", seconds=4 * WAIT_CAP_S,
                                         confirm_mode=confirm_mode, driver=driver, **run_options)
    finally:
        driver.stop()
        osel.log.removeHandler(handler)
        osel.log.setLevel(old_level)
    return session


def confirm_with_j_then_hold_until_moving(s: DriveSession):
    """Script steps shared by the tests: look at the chair, confirm with J, keep looking until the wheels turn."""
    yield from s.wait(MIN_LOOK_S + 0.2)  # a short look first, or the J press is ignored
    yield from s.until(lambda: s.logged("CONFIRMED"), "the J key to confirm the chair", key=ord("j"))
    yield from s.until(s.is_moving, "the wheels to start after the 1.5 s hold")


def test_frozen_forward_camera_stops_the_chair_and_the_screen_says_so(monkeypatch):
    """Audit finding 1: the camera froze, the rider kept looking at the frozen picture, the chair kept driving."""
    # Arrange: the chair is driving toward the confirmed object when the camera stops delivering new frames.
    def script(s: DriveSession):
        yield from confirm_with_j_then_hold_until_moving(s)
        s.freeze_camera()
        yield from s.wait(STALE_INTENT_S + 1.5)  # the rider keeps looking at the frozen picture

    # Act
    s = run_drive_session(monkeypatch, [CHAIR], script)

    # Assert: from the moment the newest frame is older than the stale limit, nothing moves and the screen says why.
    stale_from = s.frozen_frame_t + STALE_INTENT_S
    assert s.moving_lines(before=stale_from), "the chair never drove, so this run proves nothing"
    assert s.moving_lines(after=stale_from + SETTLE_S) == []
    final_status = s.statuses[-1][1]  # drawn 1.5 s after the frame went stale
    assert "CAMERA FROZEN" in final_status and "STOPPED" in final_status


class _JawOnJ:
    """A headset stand-in: J counts as a clench. Used where SPACE must stay the emergency stop (in key mode
    SPACE confirms and S stops; see test_in_key_mode_space_confirms_and_s_is_the_emergency_stop)."""
    mode, error = "synthetic", None  # practice board: the screen turns a J press into a clench

    def __init__(self):
        self.pending = False

    def inject_fake_clench(self, seconds=0.6):
        self.pending = True

    def alive(self):
        return True

    def level(self):
        return 0.1

    def take(self):
        fired, self.pending = self.pending, False
        return fired


def test_in_key_mode_space_confirms_and_s_is_the_emergency_stop():
    from vision.object_select import KEY_MODE_STOP_KEY, STOP_KEY, confirm_event, stop_key

    assert confirm_event("key", SPACE, None) and confirm_event("key", ord("j"), None)
    assert stop_key("key") == KEY_MODE_STOP_KEY == ord("s")
    assert stop_key("jaw") == stop_key("dwell") == STOP_KEY == SPACE


def test_space_latches_an_emergency_stop_until_r_rearms(monkeypatch):
    """Audit finding 3: SPACE did nothing while driving and E_STOP could not be reached in this program."""
    # Arrange: SPACE while the wheels turn; the rider keeps looking at the chair the whole time; later R.
    def script(s: DriveSession):
        yield from confirm_with_j_then_hold_until_moving(s)
        s.mark("space")
        yield SPACE
        yield from s.wait(DWELL_S + 1.0)  # without a LATCHED stop the chair would start again after the 1.5 s hold
        s.mark("rearm")
        yield ord("r")
        yield from s.until(lambda: s.moving_lines(after=s.marks["rearm"]), "the chair to move again after re-arm")

    # Act
    s = run_drive_session(monkeypatch, [CHAIR], script, confirm_mode="jaw", jaw=_JawOnJ())

    # Assert: stopped and E_STOP on screen from SPACE until R; after R a fresh 1.5 s hold, then it moves again.
    space_t, rearm_t = s.marks["space"], s.marks["rearm"]
    assert s.moving_lines(after=space_t + SETTLE_S, before=rearm_t) == []
    latched = [text for t, text in s.statuses if space_t < t < rearm_t]
    assert latched and all("E_STOP" in text for text in latched)
    first_move_again = next(t for t, line in zip(s.port.times, s.port.lines()) if line.startswith("C,") and t > rearm_t)
    assert first_move_again - rearm_t >= DWELL_S - 0.15


def test_x_cancels_the_destination_in_dwell_mode_until_the_gaze_leaves_and_comes_back(monkeypatch):
    """Audit finding 3: in dwell mode X cleared the confirmation and the same loop pass confirmed it again."""
    # Arrange: dwell mode, the chair is driving, X is pressed, the rider keeps staring at the same chair.
    def script(s: DriveSession):
        yield from s.until(s.is_moving, "the wheels to start (1.5 s dwell to confirm, then the 1.5 s hold)")
        s.mark("x")
        yield ord("x")
        yield from s.wait(DWELL_S + 1.0)  # longer than a full dwell: a re-confirmation would show up here
        s.marks["confirmed_while_staring"] = s.logged("CONFIRMED")
        s.gaze_point = EMPTY_CORNER  # the gaze leaves the chair ...
        yield from s.wait(0.3)
        s.gaze_point = CENTRE  # ... and comes back: now the chair may be chosen again
        yield from s.until(lambda: s.logged("CONFIRMED") >= 2, "the chair to be confirmed again after looking away")

    # Act
    s = run_drive_session(monkeypatch, [CHAIR], script, confirm_mode="dwell")

    # Assert
    assert s.moving_lines(after=s.marks["x"] + SETTLE_S) == []  # X stopped the chair and it stayed stopped
    assert s.marks["confirmed_while_staring"] == 1  # staring at the cancelled chair did not confirm it again
    assert sum("CONFIRMED" in line for line in s.confirmations) == 2


def test_arrival_in_dwell_mode_is_reported_once_and_the_chair_stays_stopped(monkeypatch):
    """Audit finding 14: an object already within reach was confirmed and 'arrived' on every loop pass."""
    from control.navigation import ARRIVE_M

    # Arrange: the object is already closer than the arrival distance; the rider never stops looking at it.
    near = Track(id=4, label="potted plant", conf=0.9, bbox=CHAIR.bbox, distance_m=ARRIVE_M / 2)

    def script(s: DriveSession):
        yield from s.until(lambda: s.logged("ARRIVED"), "the arrival to be reported")
        yield from s.wait(1.0)  # the bug logged dozens more CONFIRMED / ARRIVED pairs in a second like this

    # Act
    s = run_drive_session(monkeypatch, [near], script, confirm_mode="dwell")

    # Assert
    assert [line.split()[0] for line in s.confirmations] == ["CONFIRMED", "ARRIVED"]
    assert s.moving_lines() == []


def test_planner_gets_every_tracked_object_as_an_obstacle_not_only_the_boxes_on_screen(monkeypatch):
    """Audit finding 6: an object next to the target is not shown as a box (boxes must stay apart), and so the
    planner was never told about it."""
    import vision.object_select as osel

    # Arrange: a person standing right beside the chair. Their box is 10 px from the chair's, so it is not shown.
    person = Track(id=9, label="person", conf=0.8, bbox=(1070, 350, 1190, 750), distance_m=2.0)
    seen = {"obstacles": set(), "on_screen": set()}
    real_nav_step, real_hit_boxes = osel.nav_step, osel.hit_boxes

    def nav_step_spy(nav, target, others, *args, **kwargs):
        seen["obstacles"] |= {t.id for t in others}
        return real_nav_step(nav, target, others, *args, **kwargs)

    def hit_boxes_spy(targets, *args, **kwargs):
        seen["on_screen"] |= {t.id for t in targets}
        return real_hit_boxes(targets, *args, **kwargs)

    monkeypatch.setattr(osel, "nav_step", nav_step_spy)
    monkeypatch.setattr(osel, "hit_boxes", hit_boxes_spy)

    def script(s: DriveSession):
        yield from s.wait(MIN_LOOK_S + 0.2)
        yield from s.until(lambda: s.logged("CONFIRMED"), "the J key to confirm the chair", key=ord("j"))
        yield from s.until(lambda: seen["obstacles"], "the planner to run once")

    # Act
    run_drive_session(monkeypatch, [CHAIR, person], script)

    # Assert
    assert CHAIR.id in seen["on_screen"]  # the destination is choosable (overlapping objects now are too)
    assert person.id in seen["obstacles"]  # but the planner knows the person is there


# ---- the same rules without a clock: exact, instant checks of single steps


class FakeDriver:
    """Just enough of MotorDriver for one drive step: no ultrasonic reading, remembers the commands."""

    def __init__(self) -> None:
        self.sent = []

    def distance_cm(self) -> None:
        return None

    def send(self, command) -> None:
        self.sent.append(command)


def one_drive_step(ctrl, now: float, frame_t: float, **extra):
    """drive_tick() for a rider looking at the confirmed, visible chair. Returns (selection, controller, driver)."""
    from control.goto import NavState
    from vision.object_select import drive_tick

    driver = FakeDriver()
    sel = Selection(candidate=CHAIR.id, since=0.0, confirmed=CHAIR.id)
    sel, ctrl, _nav, _note = drive_tick(sel, CHAIR.id, [CHAIR], FRAME_W, 85.5, driver, ctrl, NavState(), now, [],
                                        obstacles=[CHAIR], frame_h=FRAME_H, frame_t=frame_t, **extra)
    return sel, ctrl, driver


def test_drive_step_keeps_moving_on_a_fresh_frame_and_stops_on_a_stale_one():
    from control.state_machine import ControllerState
    from shared.protocol import State, Target

    moving = ControllerState(State.MOVING, Target.FWD, dwell_start=0.0)

    _, fresh_ctrl, fresh_driver = one_drive_step(moving, now=10.0, frame_t=10.0 - STALE_INTENT_S + 0.1)
    _, stale_ctrl, stale_driver = one_drive_step(moving, now=10.0, frame_t=10.0 - STALE_INTENT_S - 0.1)

    assert fresh_ctrl.state == State.MOVING and not fresh_driver.sent[-1].stop
    assert stale_ctrl.state == State.STOPPED and stale_driver.sent[-1].stop
    assert stale_driver.sent[-1].t == 10.0  # the stop command itself is fresh, or the driver would ignore it as old


def test_drive_step_operator_stop_latches_and_only_rearm_releases_it():
    from control.state_machine import ControllerState
    from shared.protocol import State, StopRequest, StopSource, Target

    moving = ControllerState(State.MOVING, Target.FWD, dwell_start=0.0)

    _, stopped, driver = one_drive_step(moving, now=10.0, frame_t=10.0,
                                        stop_requests=(StopRequest(StopSource.OPERATOR, 10.0),))
    _, still_stopped, _ = one_drive_step(stopped, now=12.0, frame_t=12.0)  # rider keeps looking: stays latched
    _, rearmed, _ = one_drive_step(still_stopped, now=12.1, frame_t=12.1, rearm=True)

    assert stopped.state == State.E_STOP and driver.sent[-1].stop
    assert still_stopped.state == State.E_STOP
    assert rearmed.state == State.STOPPED  # re-armed means stopped and ready, never straight back to moving


@pytest.mark.parametrize("planner_takes_frame_h, expected", [(True, {"frame_h": FRAME_H}), (False, {})])
def test_drive_step_passes_the_frame_height_only_to_a_planner_that_accepts_it(monkeypatch, planner_takes_frame_h,
                                                                             expected):
    import vision.object_select as osel
    from control.goto import NavState
    from control.state_machine import ControllerState

    got = {}

    def fake_nav_step(nav, target, others, frame_w, hfov_deg, distance_cm, **kwargs):
        got.update(kwargs=kwargs)
        return NavState(), (0, 0), False

    monkeypatch.setattr(osel, "nav_step", fake_nav_step)
    monkeypatch.setattr(osel, "NAV_STEP_TAKES_FRAME_H", planner_takes_frame_h)

    one_drive_step(ControllerState(), now=10.0, frame_t=10.0)

    assert got["kwargs"] == expected


@pytest.mark.parametrize("dwell_s, confirm", [(DWELL_S, False), (None, True)])  # dwell mode, key / jaw mode
def test_cleared_destination_cannot_be_confirmed_again_until_the_gaze_leaves_it(dwell_s, confirm):
    from vision.object_select import clear_destination

    box = (0.4, 0.3, 0.6, 0.7)
    sel = clear_destination(Selection(candidate=7, since=0.0, confirmed=7, box=box))
    assert sel.confirmed is None

    sel = update_selection(sel, hit=7, now=10.0, dwell_s=dwell_s, box=box, confirm=confirm)  # still looking at it
    sel = update_selection(sel, hit=130, now=20.0, dwell_s=dwell_s, box=box, confirm=confirm)  # tracker relabels it
    sel = update_selection(sel, hit=130, now=30.0, dwell_s=dwell_s, box=box, confirm=confirm)
    assert sel.confirmed is None  # however long the rider looks (or clenches), the same object stays unconfirmed

    sel = update_selection(sel, hit=None, now=31.0, dwell_s=dwell_s)  # the gaze leaves ...
    sel = update_selection(sel, hit=130, now=32.0, dwell_s=dwell_s, box=box)  # ... and comes back
    sel = update_selection(sel, hit=130, now=32.0 + DWELL_S + 0.01, dwell_s=dwell_s, box=box, confirm=confirm)
    assert sel.confirmed == 130


def test_clearing_the_destination_does_not_block_a_different_object():
    from vision.object_select import clear_destination

    sel = clear_destination(Selection(candidate=7, since=0.0, confirmed=7, box=(0.1, 0.1, 0.3, 0.5)))
    sel = update_selection(sel, hit=9, now=1.0, box=(0.6, 0.1, 0.9, 0.5))  # eyes move straight to another object
    sel = update_selection(sel, hit=9, now=1.0 + DWELL_S + 0.01, box=(0.6, 0.1, 0.9, 0.5))
    assert sel.confirmed == 9


def test_status_line_puts_a_frozen_camera_first_and_lists_the_operator_keys_when_driving():
    from vision.object_select import status_line

    frozen = status_line("dwell", has_gaze=True, frame_age_s=STALE_INTENT_S + 1.0, must_look_away=False, driving=True)
    driving = status_line("dwell", has_gaze=True, frame_age_s=0.03, must_look_away=False, driving=True)
    choosing = status_line("dwell", has_gaze=True, frame_age_s=0.03, must_look_away=False, driving=False)

    assert "CAMERA FROZEN" in frozen and "1.5 s" in frozen  # says how old the picture is
    assert "SPACE" in driving and "R re-arm" in driving and "X cancel" in driving
    assert "SPACE" not in choosing  # without --drive there is nothing to stop


def test_session_ends_at_once_if_the_jaw_reader_dies():
    import queue
    import time

    from vision.object_select import run

    class FakeCv2:
        def waitKey(self, _ms):  # noqa: N802 - OpenCV's name
            return 255

        def imshow(self, *_args):
            pass

    class NoFrames:
        def latest(self):
            return None

    class DeadJaw:
        mode, error = "dongle", RuntimeError("board unplugged")

        def alive(self):
            return False

        def take(self):
            return False

    start = time.monotonic()
    result = run(FakeCv2(), NoFrames(), model=None, classes=None, gaze_queue=queue.Queue(), hfov=70.0,
                 device="cpu", seconds=5.0, confirm_mode="jaw", jaw=DeadJaw())
    assert result == [] and time.monotonic() - start < 1.0  # did not wait 5 s for a clench that can never come


def test_gaze_on_the_screen_maps_onto_the_camera_picture_between_the_bars():
    from vision.object_select import CANVAS_H, VIEW_H, to_view_point

    x, y = to_view_point((0.3, 0.5))
    assert x == 0.3 and 0.5 < y < 0.54  # the picture starts below the top bar, so its middle is a little lower
    assert to_view_point((0.5, 0.01)) is None and to_view_point((0.5, 0.99)) is None  # on a bar: on no object
    assert to_view_point(None) is None
    assert VIEW_H < CANVAS_H


def test_draw_returns_the_full_screen_with_bars_and_leaves_the_frame_and_tracks_alone():
    import cv2
    import numpy as np

    from vision.object_select import CANVAS_H, CANVAS_W, draw

    frame = np.full((1080, 1920, 3), 90, np.uint8)
    outline = np.array([[860, 300], [1060, 300], [1060, 800], [860, 800]], np.float32)
    chair = Track(id=4, label="chair", conf=0.9, bbox=(860, 300, 1060, 800), distance_m=2.5, outline=outline)
    before_frame, before_outline = frame.copy(), outline.copy()
    looking = Selection(candidate=4, since=0.0)

    screen = draw(cv2, frame, [chair], {}, looking, (0.5, 0.5), 1.0, "look for 1.5 s to confirm")
    idle = draw(cv2, frame, [chair], {}, Selection(), None, 1.0, "look for 1.5 s to confirm")

    assert screen.shape == (CANVAS_H, CANVAS_W, 3)
    assert not np.array_equal(screen, idle)  # the looked-at object and the cursor are drawn differently
    assert np.array_equal(frame, before_frame) and np.array_equal(outline, before_outline)


def wheel_speeds(line: str) -> tuple[int, int]:
    left, right = line.split(",")[2:]
    return int(left), int(right)


def test_route_mode_drives_the_chair_along_the_planned_route(monkeypatch):
    """--follow route: the wheels are driven by the route follower. The floor is open and the chair is dead
    ahead, so the planned route is a straight line and both wheels must run forward at the same speed."""
    def script(s: DriveSession):
        yield from confirm_with_j_then_hold_until_moving(s)
        yield from s.wait(1.0)

    s = run_drive_session(monkeypatch, [CHAIR], script, follow="route")

    moving = [wheel_speeds(line) for line in s.moving_lines()]
    assert moving, "the chair never moved along the route"
    assert all(left > 0 and right > 0 for left, right in moving)  # forward only, never a spin or a reverse
    assert all(abs(left - right) <= 16 for left, right in moving)  # straight (each wheel ramps by 8 per line)
    assert not any("no safe route" in status for _t, status in s.statuses)


def test_route_mode_keeps_the_chair_still_when_no_route_is_safe(monkeypatch):
    """--follow route with something right across the floor between the chair and the object: there is no
    route, so nothing may move, however long the rider holds the gaze. The screen says why."""
    import vision.object_select as osel

    barrier = Track(id=9, label="couch", conf=0.9, bbox=(0, 850, FRAME_W - 1, 1000), distance_m=2.0)
    # The barrier overlaps the chair sideways, and the selection rule only offers well-separated objects. Offer
    # just the chair, so the barrier is purely an obstacle (it is still in the tracks the route is planned on).

    def script(s: DriveSession):
        yield from s.wait(MIN_LOOK_S + 0.2)
        yield from s.until(lambda: s.logged("CONFIRMED"), "the J key to confirm the chair", key=ord("j"))
        yield from s.wait(DWELL_S + 1.0)  # hold well past the 1.5 s that would normally start the drive

    s = run_drive_session(monkeypatch, [CHAIR, barrier], script, follow="route")

    assert s.moving_lines() == []
    assert any("no safe route" in status for _t, status in s.statuses)


def test_direct_mode_is_still_the_default_and_ignores_routes(monkeypatch):
    """Without --follow route nothing changes: the same barrier does not stop the old planner from proposing
    motion (it steers around boxes its own way). This pins that route mode is opt-in."""
    import vision.object_select as osel

    calls = []
    monkeypatch.setattr(osel, "plan_for_drive", lambda *a, **k: calls.append(1) or (None, None))

    def script(s: DriveSession):
        yield from confirm_with_j_then_hold_until_moving(s)

    s = run_drive_session(monkeypatch, [CHAIR], script)

    assert s.is_moving() and calls == []  # drove, and never planned a route


def test_between_detections_the_planner_is_not_stepped_but_the_state_machine_still_stops_the_chair(monkeypatch):
    """Detection now runs about 7 times a second while the loop runs faster. The planner must only step on a new
    detection (its acceleration limit assumes one step per look), but looking away must still stop at once."""
    import time

    import vision.object_select as osel
    from control.goto import NavState
    from control.state_machine import ControllerState
    from motors.mock_serial import MockSerial

    calls = []
    monkeypatch.setattr(osel, "nav_step", lambda *a, **k: calls.append(1) or (NavState(0.3, 0.0), (90, 90), False))

    class Driver:
        def __init__(self):
            self.sent = []

        def distance_cm(self):
            return None

        def send(self, command):
            self.sent.append(command)

    driver, sel, now = Driver(), Selection(candidate=4, since=0.0, confirmed=4), time.monotonic()
    common = dict(obstacles=[CHAIR], frame_h=FRAME_H, frame_t=now)
    _, ctrl, nav, _ = osel.drive_tick(sel, 4, [CHAIR], FRAME_W, 85.5, driver, ControllerState(), NavState(), now, [],
                                      **common)
    _, ctrl, nav, _ = osel.drive_tick(sel, 4, [CHAIR], FRAME_W, 85.5, driver, ctrl, nav, now + 0.02, [],
                                      replan=False, **common)
    assert calls == [1]  # the second pass reused the speeds instead of stepping the planner again
    assert nav == NavState(0.3, 0.0)
    _, ctrl, nav, _ = osel.drive_tick(sel, None, [CHAIR], FRAME_W, 85.5, driver, ctrl, nav, now + 0.04, [],
                                      replan=False, **common)
    assert driver.sent[-1].stop  # looked away on a pass without a detection: stop command all the same
    assert MockSerial is not None


def test_scene_worker_publishes_detections_and_a_route_for_the_destination():
    import time

    import numpy as np

    from vision.scene_worker import SceneWorker

    frame = np.zeros((FRAME_H, FRAME_W, 3), np.uint8)

    class Camera:
        def latest(self):
            return frame, time.monotonic()

    planned = []
    worker = SceneWorker(Camera(), detect=lambda _f: [CHAIR],
                         plan=lambda _f, _t, target: planned.append(target.id) or ("route", np.ones((2, 2))),
                         period_s=0.01)
    worker.set_destination(CHAIR.id)
    worker.start()
    try:
        deadline = time.monotonic() + 5.0
        while (worker.latest() is None or worker.latest().route is None) and time.monotonic() < deadline:
            time.sleep(0.01)
        scene = worker.latest()
    finally:
        worker.stop()
    assert scene is not None and [t.id for t in scene.targets] == [CHAIR.id]
    assert scene.destination == CHAIR.id and scene.route == "route" and CHAIR.id in planned


def test_scene_worker_that_crashes_reports_itself_dead():
    import time

    import numpy as np

    from vision.scene_worker import SceneWorker

    class Camera:
        def latest(self):
            return np.zeros((10, 10, 3), np.uint8), time.monotonic()

    def broken(_frame):
        raise RuntimeError("model crashed")

    worker = SceneWorker(Camera(), detect=broken, plan=None, period_s=0.0)
    worker.start()
    deadline = time.monotonic() + 5.0
    while worker.alive() and time.monotonic() < deadline:
        time.sleep(0.01)
    worker.stop()
    assert not worker.alive() and isinstance(worker.error, RuntimeError)


def test_jaw_meter_fills_up_to_the_threshold_and_says_clench_above_it():
    from vision.object_select import jaw_meter

    assert jaw_meter(None) == "JAW: no signal"
    assert jaw_meter(0.0).count("■") == 0 and "CLENCH" not in jaw_meter(0.5)
    assert jaw_meter(0.5).count("■") == 5
    assert jaw_meter(1.4).count("■") == 10 and jaw_meter(1.4).endswith("CLENCH")


def test_confirmed_destination_is_drawn_differently_from_an_object_only_looked_at():
    import cv2
    import numpy as np

    from vision.object_select import draw

    frame = np.full((1080, 1920, 3), 90, np.uint8)
    outline = np.array([[860, 300], [1060, 300], [1060, 800], [860, 800]], np.float32)
    chair = Track(id=4, label="chair", conf=0.9, bbox=(860, 300, 1060, 800), distance_m=2.5, outline=outline)
    looking = draw(cv2, frame, [chair], {}, Selection(candidate=4, since=0.0), None, 0.1, "s")
    confirmed = draw(cv2, frame, [chair], {}, Selection(candidate=4, since=0.0, confirmed=4), None, 0.1, "s")
    inside = (slice(350, 420), slice(600, 680))  # inside the chair on the 1280 x 800 screen, away from the reticle
    assert confirmed[inside].mean() > looking[inside].mean() + 10  # the destination is filled much more strongly
