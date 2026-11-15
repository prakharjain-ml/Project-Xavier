"""Whole chain through the web session, with every stage's REAL code:

    gaze point -> object_select selection -> OpenBCI jaw detector (bci.jaw_live.JawConfirmSource on BrainFlow's
    built-in synthetic board, its own fake-clench injection) -> confirm -> SceneWorker + A* plan_for_drive ->
    drive_tick -> motors.driver.MotorDriver -> MockSerial lines.

Only the inputs are scripted: the gaze point (the eye tracker needs a face and a camera) and the camera frame +
detections (no Pixel attached). Nothing opens a camera, the real headset or a serial port.
"""

import time

import numpy as np
import pytest

from interface.web.session import Session
from interface.web.voice import SilentVoice
from interface.web.workflow import Flow
from vision.detect_track import Track
from vision.gaze import GazeSample

FRAME = np.zeros((720, 1280, 3), np.uint8)
CHAIR = Track(1, "chair", 0.9, (520.0, 330.0, 760.0, 650.0), 2.4)
COUCH = Track(2, "couch", 0.8, (860.0, 360.0, 1220.0, 560.0), 3.5)
LAYOUT = {"viewport_w": 1280, "viewport_h": 720, "screen_w": 1280, "screen_h": 720, "dpr": 2.0,
          "fullscreen": True, "video": (0.0, 0.0, 1280.0, 720.0)}


class FrameReader:
    """A camera that keeps delivering the same frame with a new arrival time (LatestFrameReader's interface)."""

    def latest(self):
        return FRAME, time.monotonic()


class ScriptedPerception:
    """Real SceneWorker + real A* planner; scripted detections and gaze."""
    kind, hfov = "live", 70.0

    def __init__(self) -> None:
        from vision.object_select import plan_for_drive
        from vision.scene_worker import SceneWorker

        self.reader = FrameReader()
        plan = lambda frame, tracks, target: plan_for_drive(frame, tracks, target, self.hfov, 0.9, 0.0)  # noqa: E731
        self.worker = SceneWorker(self.reader, lambda frame: [CHAIR, COUCH], plan, 0.1)
        self.point = (0.5, 0.7)  # gaze on the chair's centre (viewport fraction == frame fraction here)

    def start(self) -> None:
        self.worker.start()

    def stop(self) -> None:
        self.worker.stop()

    def gaze(self):
        return GazeSample(self.point, False, True, time.monotonic())

    def wheels(self, left, right, dt) -> None: ...

    def problem(self):
        return None if self.worker.alive() else f"detection stopped: {self.worker.error}"

    def devices(self):
        return {}


def synthetic_headset():
    from bci.jaw_live import JawConfirmSource

    # The real detector and calibration, sped up: 2 s relax, three 0.6 s clenches, 0.3 s rests.
    return JawConfirmSource("synthetic", relax_s=2.0, clench_s=0.6, rest_s=0.3)


def wait_for(condition, seconds: float, session: Session, beat) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        beat()
        session.tick()
        if condition():
            return True
        time.sleep(0.05)
    return False


def test_gaze_then_real_jaw_clench_then_a_star_route_drives_the_mock_chair():
    pytest.importorskip("brainflow")
    # Arrange
    perception = ScriptedPerception()
    session = Session(lambda mode, action: perception, jaw_factory=synthetic_headset, check_hardware=lambda: None,
                      voice=SilentVoice())

    client = "tab-chain0001"
    session.hello(client)
    seq = iter(range(1, 100))

    def act(kind, **fields):
        return session.act(client, {"type": kind, "seq": next(seq), "session": session.session_id, **fields})

    def beat():
        session.heartbeat(client)

    port = None
    try:
        act("start_session")
        act("layout", layout=LAYOUT)
        port = session.driver.mock_port

        # Act 1: the real jaw calibration (relax, 3 clenches) finishes and the session is ready to choose
        assert wait_for(lambda: session.flow == Flow.SELECTING, 15, session, beat), session.error

        # Act 2: look at the chair long enough, then clench (the board's own fake clench -> real detector)
        assert wait_for(lambda: session.drive.sel.candidate == CHAIR.id, 3, session, beat)
        wait_for(lambda: False, 0.4, session, beat)
        session.jaw.inject_fake_clench(0.7)
        assert wait_for(lambda: session.flow == Flow.NAVIGATING, 5, session, beat), "clench did not confirm"

        # Act 3: the A* route arrives and the wheels are told to move
        assert wait_for(lambda: session.drive.route_m is not None and not session.driver.last.stop, 5, session, beat)
        route = session.drive.route_m
        wait_for(lambda: False, 0.2, session, beat)

        # Assert
        assert session.drive.sel.confirmed == CHAIR.id
        assert len(route) >= 1 and route[-1][0] > 1.0              # A* waypoints forward (metres, chair frame)
        assert any(line.startswith("C,") for line in port.lines())  # moving lines reached the (mock) chair
    finally:
        session.shutdown()
    assert port is not None and port.lines()[-1].startswith("S,")  # and it ends on STOP
