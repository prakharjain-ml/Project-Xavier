"""Web session behaviour that matters for safety, with a scripted perception and the real MotorDriver on a
MockSerial port. Nothing here opens a camera, a headset or a serial port."""

import time

import numpy as np
import pytest

from interface.web import session as sess
from interface.web.coords import Layout
from interface.web.session import ActionError, Session
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

    def set_pointer(self, point, now) -> None:
        self.point = point

    def gaze(self):
        return GazeSample(self.point, False, self.point is not None, time.monotonic())

    def wheels(self, left, right, dt): ...

    def problem(self):
        return self.failure

    def devices(self):
        return {}


class Tab:
    """One browser tab: sends actions with increasing sequence numbers."""

    def __init__(self, session: Session, client: str) -> None:
        self.session, self.client, self.seq = session, client, 0
        session.hello(client)

    def act(self, kind: str, **fields):
        self.seq += 1
        action = {"type": kind, "seq": self.seq, "session": self.session.session_id, **fields}
        return self.session.act(self.client, action)

    def beat(self, pointer=(0.5, 0.65)) -> None:
        self.session.heartbeat(self.client, pointer)


@pytest.fixture
def setup():
    perception = FakePerception()
    session = Session(lambda mode, action: perception)
    tab = Tab(session, "tab-aaaaaaaa")
    yield session, tab, perception
    session.shutdown()


def run_ticks(session: Session, tab: Tab, n: int, pause: float = 0.03) -> None:
    for _ in range(n):
        tab.beat()
        session.tick()
        time.sleep(pause)


def drive_to_chair(session: Session, tab: Tab) -> None:
    tab.act("start_session", mode="mock", confirm="key")
    tab.act("layout", layout=LAYOUT)
    tab.act("continue")
    run_ticks(session, tab, 12)  # look at the chair long enough (MIN_LOOK_S) ...
    tab.act("confirm")           # ... then confirm
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
    tab.act("start_session", mode="mock", confirm="key")
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
    # Arrange
    session, tab, _ = setup
    tab.act("start_session", mode="mock", confirm="key")

    # Act / Assert: cannot re-arm or choose again from device setup
    with pytest.raises(ActionError):
        tab.act("rearm")
    with pytest.raises(ActionError):
        tab.act("choose_again")
    assert session.flow == Flow.DEVICE_SETUP


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
    tab.act("start_session", mode="mock", confirm="key")
    tab.act("layout", layout=LAYOUT)
    tab.act("continue")
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
