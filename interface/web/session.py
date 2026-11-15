"""The web app's one session: workflow state, typed actions from the controlling browser tab, and a 20 Hz tick that
runs the SAME selection and drive logic as vision/object_select.py (without any window).

Motion policy (decided by the human on Sun Nov 15): the current object mode (commit 708cb8a). Confirming a
destination drives to it at once, and drive_tick keeps going through short detection/route dropouts using the
remembered box and route. Added only because control now lives in a browser, never removed:
  - the controlling tab must send a heartbeat; HEARTBEAT_S without one -> STOP, destination cleared, PAUSED;
  - emergency stop latches (PAUSED) until an explicit re-arm, which authorizes nothing by itself;
  - a perception failure, a backend exception, cancel or end of session -> STOP;
  - reaching the destination (route follower says "arrived") -> STOP, destination cleared, ARRIVED.
All motion goes through motors.driver.MotorDriver, whose own thread streams STOP if the session stops sending.
This deviates from docs/SAFETY.md (no stale-frame stop, no hold-to-move) exactly as object mode does today.
"""

from __future__ import annotations

import collections
import logging
import threading
import time
import uuid
from dataclasses import dataclass, field

import numpy as np

from interface.web.coords import Layout, geometry_changed, screen_matches_viewport, viewport_to_frame
from interface.web.workflow import DRIVABLE, Flow, IllegalTransition, check
from shared.protocol import MotorCommand

log = logging.getLogger("interface.web.session")

TICK_HZ = 20.0
HEARTBEAT_S = 0.5        # controlling tab silent this long -> STOP (server-side deadline, not a browser timer)
LEASE_S = 3.0            # a silent controller loses control after this long (another tab may take over)
EVENTS_KEPT = 30         # recent events shown in the app (bounded)
DWELL_CONFIRM_S = 1.5    # dwell mode: same as shared.protocol.DWELL_S via object_select.confirm_settings
CONFIRM_MODES = ("dwell", "key", "blink", "jaw")


class ActionError(ValueError):
    """An action that is not allowed now (wrong session, state, or not the controller)."""


@dataclass
class Client:
    id: str
    last_beat: float
    last_seq: int = -1


@dataclass
class Drive:
    """Everything the object-mode loop carries from one pass to the next (see object_select.run)."""
    sel: object = None
    memory: object = None
    ctrl: object = None
    nav: object = None
    blink: object = None
    series: object = None
    euro: object = None
    offset: tuple[float, float] = (0.0, 0.0)
    hit: int | None = None
    last_sample: object = None
    frame_t: float | None = None
    frame_size: tuple[int, int] = (0, 0)
    tracks: list = field(default_factory=list)
    targets: list = field(default_factory=list)
    route_m: np.ndarray | None = None
    planned_for: int | None = None
    held: bool = False
    pending_confirm: bool = False
    arrow: object = None  # manual mode: the arrow the gaze is on (shared.protocol.Target) or None
    named: bool = False   # the confirm announcement already named the destination ("Driving to the chair")
    route_said: str | None = None  # last route state announced, so each is said once per destination
    wheels: tuple[int, int] = (0, 0)
    note: str = ""
    gaze_point: tuple[float, float] | None = None   # viewport fraction (for drawing)
    gaze_age_s: float | None = None


def _fresh_drive() -> Drive:
    from control.goto import NavState
    from control.state_machine import ControllerState
    from vision.object_select import BlinkConfirm, BlinkSeries, DestinationMemory, Selection
    from vision.smoothing import EuroState

    return Drive(Selection(), DestinationMemory(), ControllerState(), NavState(), BlinkConfirm(), BlinkSeries(),
                 EuroState())


class RecordingDriver:
    """Wraps a MotorDriver and remembers the newest command (for the display and the practice-room simulation)."""

    def __init__(self, inner, port_label: str) -> None:
        self.inner, self.port_label = inner, port_label
        self.last = MotorCommand.halt(time.monotonic())

    def send(self, command: MotorCommand) -> None:
        self.last = command
        self.inner.send(command)

    def distance_cm(self):
        return self.inner.distance_cm()

    def start(self) -> None:
        self.inner.start()

    def stop(self) -> None:
        self.inner.stop()


def mock_driver() -> RecordingDriver:
    from motors.driver import MotorDriver
    from motors.mock_serial import MockSerial

    port = MockSerial()
    driver = RecordingDriver(MotorDriver(lambda: port), "mock")
    driver.mock_port = port  # tests read the lines the "chair" received
    return driver


def real_jaw():
    """The OpenBCI Cyton over its Wi-Fi shield, channels 1 and 2 (the same board and channels as demo.sh jaw)."""
    from bci.jaw_live import JawConfirmSource

    return JawConfirmSource("wifi", channels=(1, 2))


def hardware_problem() -> str | None:
    """Why a session cannot start: the phone camera or the headset is missing (read-only checks, no port opened)."""
    from interface.launcher_modes import headset_ready, room_camera_ready

    if not room_camera_ready():
        return "Phone camera not connected. Plug in the Pixel (USB webcam), then start again."
    if not headset_ready():
        return "Headset not connected. Join the OpenBCI-xxxx Wi-Fi and close the OpenBCI GUI, then start again."
    return None


class Session:
    def __init__(self, perception_factory, driver_factory=mock_driver, clock=time.monotonic,
                 jaw_factory=real_jaw, check_hardware=hardware_problem, voice=None) -> None:
        self._make_perception, self._make_driver, self._clock = perception_factory, driver_factory, clock
        self._make_jaw, self._check_hardware = jaw_factory, check_hardware
        if voice is None:
            from interface.web.voice import Voice

            voice = Voice()
        self.voice = voice  # spoken announcements of what the chair will do (information only)
        self.jaw_prompt: str | None = None
        self.drive_mode = "auto"  # auto = path finding to a confirmed object; manual = gaze arrows
        self._lock = threading.RLock()
        self.flow = Flow.IDLE
        self.session_id: str | None = None
        self.mode, self.confirm = "mock", "dwell"
        self.perception = None
        self.driver: RecordingDriver | None = None
        self.jaw = None
        self.drive = _fresh_drive()
        self.layout: Layout | None = None
        self.calibration_layout: Layout | None = None
        self.calibrated = False
        self.estop_reason: str | None = None
        self.error: str | None = None
        self.arrived_at: str | None = None
        self.controller: Client | None = None
        self.clients: dict[str, Client] = {}
        self.events: collections.deque = collections.deque(maxlen=EVENTS_KEPT)
        self.tick_ms = 0.0
        self._last_tick = clock()

    # ------------------------------------------------------------ helpers
    def _event(self, text: str, tone: str = "info") -> None:
        self.events.append({"t": round(self._clock(), 2), "text": text, "tone": tone})
        log.info("%s", text)

    def _go(self, target: Flow) -> None:
        self.flow = check(self.flow, target)

    def _halt(self) -> None:
        if self.driver is not None:
            self.driver.send(MotorCommand.halt(self._clock()))
        self.drive.wheels = (0, 0)

    def _clear_destination(self) -> None:
        from vision.object_select import clear_destination

        self.drive.sel = clear_destination(self.drive.sel)
        worker = getattr(self.perception, "worker", None) if self.perception is not None else None
        if worker is not None:
            worker.set_destination(None)
        self.drive.route_m, self.drive.planned_for = None, None

    def controller_fresh(self, now: float) -> bool:
        return self.controller is not None and now - self.controller.last_beat <= HEARTBEAT_S

    # ------------------------------------------------------------ clients
    def hello(self, client_id: str) -> dict:
        """A tab connected. The first tab (or any tab once the controller is gone) controls; others only watch."""
        with self._lock:
            now = self._clock()
            client = self.clients.setdefault(client_id, Client(client_id, now))
            client.last_beat = now
            if self.controller is None or now - self.controller.last_beat > LEASE_S:
                self.controller = client
            return {"client": client_id, "controller": self.controller.id == client_id}

    def heartbeat(self, client_id: str, pointer: tuple[float, float] | None = None) -> None:
        with self._lock:
            now = self._clock()
            client = self.clients.get(client_id)
            if client is None:
                return
            client.last_beat = now

    def take_control(self, client_id: str) -> None:
        with self._lock:
            now = self._clock()
            if self.controller is not None and self.controller.id != client_id \
                    and now - self.controller.last_beat <= LEASE_S:
                raise ActionError("Another window is controlling Xavier. Close it first.")
            self.controller = self.clients.get(client_id) or Client(client_id, now)
            self.clients[client_id] = self.controller
            if self.flow in DRIVABLE and self.drive.sel.confirmed is not None:
                self._pause("Control moved to another window")

    # ------------------------------------------------------------ actions
    def act(self, client_id: str, action: dict) -> dict:
        """Run one typed action (already schema-checked by contracts.py). Raises ActionError if not allowed."""
        with self._lock:
            client = self.clients.get(client_id)
            if client is None or self.controller is None or self.controller.id != client_id:
                raise ActionError("This window is only watching. Take control first.")
            seq = action["seq"]
            if seq <= client.last_seq:
                raise ActionError("Duplicate or late action ignored")
            client.last_seq = seq
            kind = action["type"]
            if kind != "start_session" and action.get("session") != self.session_id:
                raise ActionError("That action belongs to an earlier session")
            handler = getattr(self, f"_do_{kind}", None)
            if handler is None:
                raise ActionError(f"Unknown action {kind}")
            try:
                handler(action)
            except IllegalTransition as error:
                raise ActionError(f"Not possible right now ({error})") from error
            return {"ok": True, "session": self.session_id}

    def _do_start_session(self, a: dict) -> None:
        """Phone camera + headset required (no simulated inputs). Confirm = jaw clench. Then the jaw calibration
        runs on its own thread while the page shows its prompts."""
        if self.flow not in (Flow.IDLE, Flow.SESSION_ENDED):
            raise ActionError("A session is already running")
        problem = self._check_hardware()
        if problem is not None:
            raise ActionError(problem)
        perception = self._make_perception("live", a)  # may raise ActionError (cameras, calibration)
        try:
            jaw = self._make_jaw()  # connects to the board: raises if it does not answer
        except Exception as error:
            raise ActionError(f"Headset did not answer ({error}). Switch the Cyton off and on, rejoin its "
                              "Wi-Fi, then start again.") from error
        self._go(Flow.DEVICE_SETUP)
        self.session_id, self.mode, self.confirm = uuid.uuid4().hex[:12], "live", "jaw"
        self.drive, self.error, self.estop_reason, self.arrived_at = _fresh_drive(), None, None, None
        self.calibrated = True  # the saved eye calibration (make_perception refuses to start without one)
        self.perception, self.jaw = perception, jaw
        self.driver = self._make_driver()
        self.driver.start()  # streams STOP lines from now on
        self.perception.start()
        self._go(Flow.JAW_CALIBRATION)
        threading.Thread(target=self._calibrate_jaw, args=(self.session_id, jaw), name="jaw-calibration",
                         daemon=True).start()
        self._event("Session started")

    def _calibrate_jaw(self, session_id: str, jaw) -> None:
        """bci.jaw_live.JawConfirmSource.calibrate, unchanged: relax, 3 clenches, threshold. Its prompts go to the
        page. A result for a session that has since ended or been replaced is ignored."""
        def show(text: str) -> None:
            self.jaw_prompt = text

        try:
            jaw.calibrate(show)
        except Exception as error:  # ValueError = contact too poor; anything else = board trouble
            with self._lock:
                if self.session_id == session_id and self.flow == Flow.JAW_CALIBRATION:
                    self._fail(f"Jaw calibration failed: {error}")
            return
        with self._lock:
            if self.session_id != session_id or self.flow != Flow.JAW_CALIBRATION:
                return  # cancelled or a newer session: never resurrect it
            jaw.start()
            self.jaw_prompt = None
            self._go(Flow.READY)
            self._go(Flow.SELECTING)
            self._event("Ready: look at a destination, then clench")

    def _do_continue(self, a: dict) -> None:
        """Next setup step: eye calibration if needed, then ready to choose."""
        if self.flow not in (Flow.DEVICE_SETUP, Flow.EYE_VALIDATION, Flow.JAW_CALIBRATION):
            raise ActionError("Nothing to continue")
        if not self.calibrated:
            self._go(Flow.EYE_CALIBRATION)
            return
        self._go(Flow.READY)
        self._go(Flow.SELECTING)
        self._event("Ready: look at an object to choose it")

    def _do_confirm(self, a: dict) -> None:
        if self.flow != Flow.SELECTING:
            raise ActionError("Confirm works while choosing a destination")
        if self.confirm not in ("key", "blink"):
            raise ActionError(f"In {self.confirm} mode, confirm with the {self.confirm}")
        self.drive.pending_confirm = True

    def _do_cancel_destination(self, a: dict) -> None:
        self._clear_destination()
        self._halt()
        if self.flow in (Flow.NAVIGATING, Flow.ARRIVED):
            self._go(Flow.SELECTING)
        self._event("Destination cancelled")

    def _do_set_drive_mode(self, a: dict) -> None:
        """Switch between automatic (path finding) and manual (gaze arrows). Always stops and clears first."""
        mode = a.get("drive_mode")
        if mode not in ("auto", "manual"):
            raise ActionError("Drive mode must be auto or manual")
        if self.flow not in (Flow.SELECTING, Flow.NAVIGATING, Flow.READY):
            raise ActionError("Switch modes while driving or choosing")
        self._clear_destination()
        self._halt()
        self.drive.arrow = None
        if self.flow == Flow.NAVIGATING:
            self._go(Flow.SELECTING)
        self.drive_mode = mode
        self._event("Manual control: look at an arrow" if mode == "manual" else "Automatic: look at a destination, then clench")

    def _do_choose_again(self, a: dict) -> None:
        self._go(Flow.SELECTING)
        self.arrived_at = None

    def _do_estop(self, a: dict) -> None:
        self._pause("Emergency stop")

    def _do_rearm(self, a: dict) -> None:
        if self.flow != Flow.PAUSED:
            raise ActionError("Nothing to re-arm")
        self.estop_reason = None
        self._go(Flow.SELECTING)  # choosing again; nothing moves until a new destination is confirmed
        self._event("Re-armed. Choose a destination to move again.", "success")

    def _do_recenter(self, a: dict) -> None:
        sample = self.perception.gaze() if self.perception is not None else None
        if sample is None or sample.point is None:
            raise ActionError("No gaze to re-centre")
        self.drive.offset = (0.5 - sample.point[0], 0.5 - sample.point[1])
        self._event("Gaze re-centred")

    def _do_layout(self, a: dict) -> None:
        layout = Layout(**a["layout"])
        if self.mode == "live" and self.calibrated and self.calibration_layout is not None \
                and geometry_changed(self.calibration_layout, layout):
            self.calibrated = False
            if self.flow in DRIVABLE:
                self._pause("Screen changed (fullscreen, zoom or display). Recalibrate the eyes.")
        self.layout = layout

    def _do_end_session(self, a: dict) -> None:
        self.shutdown("Session ended")

    # ------------------------------------------------------------ stop paths
    def _pause(self, reason: str) -> None:
        self._clear_destination()
        self._halt()
        self.estop_reason = reason
        if self.flow not in (Flow.PAUSED, Flow.IDLE, Flow.SESSION_ENDED, Flow.ERROR):
            self._go(Flow.PAUSED)
            self.voice.announce("estop" if reason == "Emergency stop" else "stop")
        self._event(f"Stopped: {reason}", "warn")

    def _fail(self, message: str) -> None:
        self._clear_destination()
        self._halt()
        self.error = message
        if self.flow not in (Flow.ERROR, Flow.IDLE, Flow.SESSION_ENDED):
            self._go(Flow.ERROR)
        self._event(message, "warn")

    def shutdown(self, reason: str = "Shutting down") -> None:
        with self._lock:
            self._halt()
            if self.jaw is not None:
                self.jaw.stop()
            if self.perception is not None:
                self.perception.stop()
            if self.driver is not None:
                self.driver.stop()  # sends its final explicit STOP lines
            self.perception, self.driver, self.jaw = None, None, None
            if self.flow not in (Flow.IDLE, Flow.SESSION_ENDED):
                self.flow = check(self.flow, Flow.SESSION_ENDED)
            self.session_id = None
            self._event(reason)

    # ------------------------------------------------------------ the tick
    def tick(self) -> None:
        """One pass, TICK_HZ times a second. Never raises: an exception stops the chair and shows an error."""
        with self._lock:
            started = self._clock()
            try:
                self._tick(started)
            except Exception as error:  # a bug here must stop the chair, not keep the last command going
                log.exception("session tick failed")
                self._fail(f"Internal error: {error}. The chair was stopped.")
            self.tick_ms = (self._clock() - started) * 1000

    def _tick(self, now: float) -> None:
        dt, self._last_tick = now - self._last_tick, now
        if self.perception is None or self.driver is None:
            return
        problem = self.perception.problem()
        if problem is None and self.jaw is not None and hasattr(self.jaw, "alive") and not self.jaw.alive():
            problem = f"Headset connection lost ({getattr(self.jaw, 'error', '')}). Reconnect and start again."
        if problem is not None and self.flow != Flow.ERROR:
            self._fail(problem)
            return
        if self.flow in DRIVABLE and not self.controller_fresh(now) and self.drive.sel.confirmed is not None:
            self._pause("Lost contact with the controlling window")
        self._update_scene()
        if self.flow not in DRIVABLE:
            self._halt()
            return
        self._select_and_drive(now)
        self.perception.wheels(*self.drive.wheels, min(dt, 0.2))

    def _update_scene(self) -> None:
        from vision.object_select import hold_destination

        d = self.drive
        worker = getattr(self.perception, "worker", None)
        scene = worker.latest() if worker is not None else None
        if scene is None or scene.frame_t == d.frame_t:
            return
        d.frame_t, d.frame_size = scene.frame_t, (scene.frame.shape[1], scene.frame.shape[0])
        d.tracks, d.targets, d.planned_for = scene.tracks, scene.targets, scene.destination
        route_m = scene.route_m if scene.destination == d.sel.confirmed else None  # never another target's route
        d.memory, d.targets, _, d.route_m, d.held = hold_destination(d.memory, d.targets, None, route_m,
                                                                     d.sel.confirmed, d.frame_t)

    def _gaze_frame_point(self, now: float):
        """Newest gaze: (sample, viewport point, frame point). Points are None when stale / no face / off picture."""
        from vision.object_select import corrected_point
        from vision.smoothing import one_euro

        d = self.drive
        sample = self.perception.gaze()
        point = corrected_point(sample, d.offset, now)
        if point is not None and self.mode == "live" and (self.layout is None
                                                          or not screen_matches_viewport(self.layout)):
            point = None  # live gaze is a screen fraction: only meaningful in fullscreen (coords.py rule 2)
        d.euro, point = one_euro(d.euro, point, now)
        d.gaze_point, d.gaze_age_s = point, (None if sample is None else round(now - sample.t, 3))
        if self.layout is None or d.frame_size == (0, 0):
            return sample, None
        return sample, viewport_to_frame(point, self.layout, *d.frame_size)

    def _select_and_drive(self, now: float) -> None:
        from control.follow import follow_step
        from vision.object_select import drive_tick, hit_boxes, nearest_target, update_selection

        d = self.drive
        if d.frame_t is None:
            self._halt()
            return
        _, frame_point = self._gaze_frame_point(now)
        if self.drive_mode == "manual":
            self._manual(frame_point, now)
            return
        boxes = hit_boxes(d.targets, *d.frame_size)
        locked = d.sel.confirmed is not None
        if locked:
            d.hit = d.sel.confirmed if any(t.id == d.sel.confirmed for t in d.targets) else None
        else:
            d.hit = nearest_target(frame_point, boxes, d.hit) if frame_point is not None else None
        confirm = (d.pending_confirm or self._jaw_fired()) and not locked  # a jaw clench confirms
        d.pending_confirm = False
        before = d.sel.confirmed
        if not locked:
            dwell_s = DWELL_CONFIRM_S if self.confirm == "dwell" else None
            d.sel = update_selection(d.sel, d.hit, now, box=boxes.get(d.hit) if d.hit is not None else None,
                                     dwell_s=dwell_s, confirm=confirm)
        if d.sel.confirmed is not None and d.sel.confirmed != before:
            chosen = next(t for t in d.targets if t.id == d.sel.confirmed)
            self._go(Flow.NAVIGATING)
            self._event(f"Destination: {chosen.label}", "success")
            d.named = self.voice.destination(chosen.label)
            d.route_said = None
        self.perception.worker.set_destination(d.sel.confirmed)
        target = next((t for t in d.targets if t.id == d.sel.confirmed), None)
        if target is not None:
            self._announce_route(target, now)
        if target is not None and d.route_m is not None and follow_step(d.route_m)[1]:
            self._arrive(target.label)
            return
        d.sel, d.ctrl, d.nav, d.note = drive_tick(d.sel, d.hit, d.targets, d.frame_size[0], self.perception.hfov,
                                                  self.driver, d.ctrl, d.nav, now, [], obstacles=d.tracks,
                                                  frame_h=d.frame_size[1], frame_t=d.frame_t, follow="route",
                                                  route_m=d.route_m, route_pending=d.planned_for != d.sel.confirmed)
        last = self.driver.last
        d.wheels = (0, 0) if last.stop else (last.left, last.right)

    def _announce_route(self, target, now: float) -> None:
        """Say each route state once per destination: planning (if it takes a moment), driving, or no route."""
        d = self.drive
        if d.route_m is not None:
            state = "driving"
        elif d.planned_for == d.sel.confirmed:
            state = "no_route"  # the planner answered for this destination and found nothing
        elif d.sel.since is not None and now - d.sel.since > 1.0:
            state = "planning"
        else:
            return
        if state == d.route_said:
            return
        d.route_said = state
        if state == "driving" and d.named:
            return  # "Driving to the chair" was already said on confirm
        self.voice.announce(state)

    def _manual(self, frame_point, now: float) -> None:
        """Manual mode, exactly as object_select's manual arrows: looking at an arrow drives that way at once
        (vision.object_select.manual_tick); looking anywhere else stops."""
        from control.state_machine import ControllerState
        from vision.manual_arrows import arrow_at
        from vision.object_select import manual_tick

        d = self.drive
        self._jaw_fired()  # drain clenches: in manual mode a clench chooses nothing
        arrow = arrow_at(frame_point)
        if arrow is not None and arrow != d.arrow:
            self.voice.announce(f"manual_{arrow.value}")  # say it once, when the direction starts
        d.arrow = arrow
        if d.arrow is not None:
            d.ctrl, d.note = manual_tick(d.arrow, self.driver, d.ctrl, now)
        else:
            self._halt()
            d.ctrl, d.note = ControllerState(), ""
        last = self.driver.last
        d.wheels = (0, 0) if last.stop else (last.left, last.right)

    def _arrive(self, label: str) -> None:
        self._clear_destination()
        self._halt()
        self.arrived_at = label
        self._go(Flow.ARRIVED)
        self._event(f"Arrived at {label}", "success")
        self.voice.announce("arrived")

    def _jaw_fired(self) -> bool:
        return self.confirm == "jaw" and self.jaw is not None and self.jaw.take()
