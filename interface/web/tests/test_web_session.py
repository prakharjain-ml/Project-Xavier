"""Web session behaviour that matters for safety, with a scripted perception and the real MotorDriver on a
MockSerial port. Nothing here opens a camera, a headset or a serial port."""

import time

import numpy as np
import pytest

from interface.web import session as sess
from interface.web.coords import Layout
from interface.web.session import ActionError, Session
from interface.web.voice import SilentVoice
from interface.web.workflow import Flow
from vision.detect_track import Track
from vision.gaze import GazeSample
from vision.scene_worker import Scene

FRAME = np.zeros((720, 1280, 3), np.uint8)
CHAIR = Track(1, "chair", 0.9, (500.0, 300.0, 780.0, 650.0), 2.0)
ROUTE = np.array([[0.5, 0.0], [1.0, 0.0], [1.6, 0.0]])
LAYOUT = {"viewport_w": 1280, "viewport_h": 720, "screen_w": 1280, "screen_h": 720, "dpr": 2.0,
          "fullscreen": True, "video": (0.0, 0.0, 1280.0, 720.0)}


class FakeWorker:
    def __init__(self) -> None:
        self.destination = None

    def latest(self) -> Scene:
        route = ROUTE if self.destination == CHAIR.id else None
        return Scene(FRAME, time.monotonic(), [CHAIR], [CHAIR], self.destination, None, route)

    def set_destination(self, target_id) -> None:
        self.destination = target_id

    def alive(self) -> bool:
        return True


class FakePerception:
    kind, hfov = "mock", 70.0

    def __init__(self) -> None:
        self.worker, self.failure, self.point = FakeWorker(), None, None

    def start(self): ...

    def stop(self): ...

    def gaze(self):
        return GazeSample(self.point, False, self.point is not None, time.monotonic())

    def wheels(self, left, right, dt): ...

    def problem(self):
        return self.failure

    def devices(self):
        return {}


class FakeJaw:
    """Stands in for bci.jaw_live.JawConfirmSource: same calibrate/start/take/level/alive/stop interface."""

    def __init__(self, fail: str | None = None, hold: float = 0.0) -> None:
        self.fail, self.hold, self.fire, self.started, self.dead = fail, hold, False, False, False

    def calibrate(self, show) -> float:
        show("Relax your jaw, teeth apart (10 s)")
        time.sleep(self.hold)
        if self.fail:
            raise ValueError(self.fail)
        show("CLENCH your jaw now (1/3)")
        return 20.0

    def start(self) -> None:
        self.started = True

    def take(self) -> bool:
        fired, self.fire = self.fire, False
        return fired

    def level(self):
        return 0.4

    def alive(self) -> bool:
        return not self.dead

    def stop(self) -> None: ...


class Tab:
    """One browser tab: sends actions with increasing sequence numbers."""

    def __init__(self, session: Session, client: str) -> None:
        self.session, self.client, self.seq = session, client, 0
        session.hello(client)

    def act(self, kind: str, **fields):
        self.seq += 1
        action = {"type": kind, "seq": self.seq, "session": self.session.session_id, **fields}
        return self.session.act(self.client, action)

    def beat(self) -> None:
        self.session.heartbeat(self.client)


@pytest.fixture
def setup():
    perception, jaw = FakePerception(), FakeJaw()
    perception.point = (0.5, 0.65)  # the rider looks at the chair
    session = Session(lambda mode, action: perception, jaw_factory=lambda: jaw, check_hardware=lambda: None,
                      voice=SilentVoice())
    session.fake_jaw = jaw
    tab = Tab(session, "tab-aaaaaaaa")
    yield session, tab, perception
    session.shutdown()


def start_and_calibrate(session: Session, tab: "Tab") -> None:
    tab.act("start_session")
    tab.act("layout", layout=LAYOUT)
    deadline = time.monotonic() + 2
    while session.flow != Flow.SELECTING and time.monotonic() < deadline:
        time.sleep(0.02)
    assert session.flow == Flow.SELECTING


def run_ticks(session: Session, tab: Tab, n: int, pause: float = 0.03) -> None:
    for _ in range(n):
        tab.beat()
        session.tick()
        time.sleep(pause)


def drive_to_chair(session: Session, tab: Tab) -> None:
    start_and_calibrate(session, tab)
    run_ticks(session, tab, 12)  # look at the chair long enough (MIN_LOOK_S) ...
    session.fake_jaw.fire = True  # ... then clench
    run_ticks(session, tab, 4, 0.02)


def test_confirm_starts_navigating_and_sends_wheel_commands(setup):
    # Arrange
    session, tab, _ = setup

    # Act
    drive_to_chair(session, tab)

    # Assert
    assert session.flow == Flow.NAVIGATING
    assert not session.driver.last.stop and session.driver.last.left > 0


def test_heartbeat_loss_stops_the_chair_and_needs_a_rearm(setup):
    # Arrange
    session, tab, _ = setup
    drive_to_chair(session, tab)

    # Act: the tab goes quiet past the deadline, then comes back
    time.sleep(sess.HEARTBEAT_S + 0.1)
    session.tick()
    run_ticks(session, tab, 2)

    # Assert: stopped, destination gone, still paused (a reconnect never resumes motion)
    assert session.flow == Flow.PAUSED and session.driver.last.stop
    assert session.drive.sel.confirmed is None


def test_emergency_stop_latches_until_rearm_and_rearm_does_not_move(setup):
    # Arrange
    session, tab, _ = setup
    drive_to_chair(session, tab)

    # Act
    tab.act("estop")
    run_ticks(session, tab, 3)
    paused = session.flow
    tab.act("rearm")
    run_ticks(session, tab, 2)

    # Assert
    assert paused == Flow.PAUSED
    assert session.flow == Flow.SELECTING and session.drive.sel.confirmed is None and session.driver.last.stop


def test_actions_from_an_old_session_duplicates_and_watching_tabs_are_refused(setup):
    # Arrange
    session, tab, _ = setup
    tab.act("start_session")
    other = Tab(session, "tab-bbbbbbbb")

    # Act / Assert
    with pytest.raises(ActionError, match="earlier session"):
        session.act(tab.client, {"type": "estop", "seq": 99, "session": "old-session"})
    with pytest.raises(ActionError, match="Duplicate"):
        session.act(tab.client, {"type": "estop", "seq": 1, "session": session.session_id})
    with pytest.raises(ActionError, match="watching"):
        other.act("estop")
    tab.beat()
    with pytest.raises(ActionError, match="Another window"):
        session.take_control(other.client)


def test_illegal_workflow_moves_are_refused(setup):
    # Arrange: a calibration that takes a while, so the session is still calibrating
    session, tab, _ = setup
    session.fake_jaw.hold = 0.5
    tab.act("start_session")

    # Act / Assert: cannot re-arm or choose again while the headset is being calibrated
    with pytest.raises(ActionError):
        tab.act("rearm")
    with pytest.raises(ActionError):
        tab.act("choose_again")
    assert session.flow == Flow.JAW_CALIBRATION


def test_perception_failure_stops_and_shows_an_error(setup):
    # Arrange
    session, tab, perception = setup
    drive_to_chair(session, tab)

    # Act
    perception.failure = "The eye tracker stopped."
    session.tick()

    # Assert
    assert session.flow == Flow.ERROR and session.driver.last.stop and "eye tracker" in session.error


def test_a_crash_inside_the_tick_stops_the_chair(setup, monkeypatch):
    # Arrange
    session, tab, _ = setup
    drive_to_chair(session, tab)
    monkeypatch.setattr(session, "_select_and_drive", lambda now: 1 / 0)

    # Act
    run_ticks(session, tab, 1)

    # Assert
    assert session.flow == Flow.ERROR and session.driver.last.stop


def test_a_route_planned_for_another_destination_is_never_taken(setup):
    # Arrange
    session, tab, perception = setup
    start_and_calibrate(session, tab)
    run_ticks(session, tab, 3)

    # Act: a scene planned for the chair arrives while nothing is confirmed
    perception.worker.destination = CHAIR.id
    run_ticks(session, tab, 1, 0)

    # Assert
    assert session.drive.sel.confirmed is None and session.drive.route_m is None and session.driver.last.stop


def test_ending_the_session_sends_stop_lines_and_releases_the_driver(setup):
    # Arrange
    session, tab, _ = setup
    drive_to_chair(session, tab)
    port = session.driver.mock_port
    time.sleep(0.15)  # let the driver thread write a few moving lines

    # Act
    tab.act("end_session")

    # Assert
    assert session.flow == Flow.SESSION_ENDED and session.driver is None
    assert any(line.startswith("C,") for line in port.lines())
    assert port.lines()[-1].startswith("S,")


def test_screen_change_in_live_mode_invalidates_calibration_and_stops(setup):
    # Arrange
    session, tab, _ = setup
    drive_to_chair(session, tab)
    session.mode, session.calibrated = "live", True
    session.calibration_layout = Layout(**LAYOUT)

    # Act: the rider leaves fullscreen
    tab.act("layout", layout={**LAYOUT, "fullscreen": False})

    # Assert
    assert not session.calibrated and session.flow == Flow.PAUSED and session.driver.last.stop


def test_session_refuses_to_start_without_the_phone_or_the_headset():
    # Arrange
    session = Session(lambda mode, action: FakePerception(), jaw_factory=FakeJaw,
                      check_hardware=lambda: "Phone camera not connected. Plug in the Pixel (USB webcam).")
    tab = Tab(session, "tab-cccccccc")

    # Act / Assert
    with pytest.raises(ActionError, match="Phone camera not connected"):
        tab.act("start_session")
    assert session.flow == Flow.IDLE and session.driver is None


def test_session_refuses_to_start_when_the_headset_does_not_answer():
    # Arrange
    def no_board():
        raise RuntimeError("BOARD_WRITE_ERROR:4 unable to prepare streaming session")

    session = Session(lambda mode, action: FakePerception(), jaw_factory=no_board, check_hardware=lambda: None)
    tab = Tab(session, "tab-dddddddd")

    # Act / Assert
    with pytest.raises(ActionError, match="Headset did not answer"):
        tab.act("start_session")
    assert session.flow == Flow.IDLE


def test_failed_jaw_calibration_shows_an_error_and_never_drives():
    # Arrange
    session = Session(lambda mode, action: FakePerception(), check_hardware=lambda: None, voice=SilentVoice(),
                      jaw_factory=lambda: FakeJaw(fail="headset signal is dead: channel 1 is flat"))
    tab = Tab(session, "tab-eeeeeeee")

    # Act
    tab.act("start_session")
    time.sleep(0.2)

    # Assert
    assert session.flow == Flow.ERROR and "channel 1 is flat" in session.error and session.driver.last.stop
    session.shutdown()


def test_a_cancelled_jaw_calibration_cannot_bring_the_session_back():
    # Arrange: calibration still running when the rider cancels
    session = Session(lambda mode, action: FakePerception(), check_hardware=lambda: None, voice=SilentVoice(),
                      jaw_factory=lambda: FakeJaw(hold=0.3))
    tab = Tab(session, "tab-ffffffff")
    tab.act("start_session")

    # Act
    tab.act("end_session")
    time.sleep(0.5)  # the calibration thread finishes after the cancel

    # Assert
    assert session.flow == Flow.SESSION_ENDED


def test_headset_connection_loss_stops_the_chair(setup):
    # Arrange
    session, tab, _ = setup
    drive_to_chair(session, tab)

    # Act
    session.fake_jaw.dead = True
    session.tick()

    # Assert
    assert session.flow == Flow.ERROR and "Headset connection lost" in session.error and session.driver.last.stop


def test_manual_mode_drives_while_looking_at_an_arrow_and_stops_when_looking_away(setup):
    # Arrange
    session, tab, perception = setup
    start_and_calibrate(session, tab)
    tab.act("set_drive_mode", drive_mode="manual")

    # Act: look at the forward arrow (top centre of the picture), then away from every arrow
    perception.point = (0.5, 0.08)
    run_ticks(session, tab, 3)
    forward = (session.driver.last.left, session.driver.last.right, session.driver.last.stop)
    perception.point = (0.5, 0.5)
    run_ticks(session, tab, 2)

    # Assert
    assert forward[0] > 0 and forward[1] > 0 and not forward[2]
    assert session.driver.last.stop and session.drive.arrow is None


def test_a_clench_in_manual_mode_chooses_no_destination(setup):
    # Arrange
    session, tab, _ = setup
    start_and_calibrate(session, tab)
    tab.act("set_drive_mode", drive_mode="manual")

    # Act
    session.fake_jaw.fire = True
    run_ticks(session, tab, 3)

    # Assert
    assert session.drive.sel.confirmed is None and session.flow == Flow.SELECTING


def test_switching_modes_stops_and_clears_the_destination(setup):
    # Arrange
    session, tab, _ = setup
    drive_to_chair(session, tab)

    # Act
    tab.act("set_drive_mode", drive_mode="manual")

    # Assert
    assert session.flow == Flow.SELECTING and session.drive.sel.confirmed is None and session.driver.last.stop
    assert session.drive_mode == "manual"


def test_the_chair_announces_what_it_will_do(setup):
    # Arrange
    session, tab, perception = setup

    # Act: confirm the chair, then switch to manual and look at the forward arrow
    drive_to_chair(session, tab)
    tab.act("set_drive_mode", drive_mode="manual")
    perception.point = (0.5, 0.08)
    run_ticks(session, tab, 3)

    # Assert
    assert session.voice.said[:2] == ["drive_chair", "manual_FWD"]


def test_every_named_clip_exists_on_disk():
    from interface.web.voice import CLIPS_DIR, PHRASES

    missing = [clip for clip, _ in PHRASES.values() if clip is not None and not (CLIPS_DIR / clip).is_file()]
    assert missing == []
