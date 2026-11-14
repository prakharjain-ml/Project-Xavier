"""Choose a real object by looking at it (gaze fallback, Mode 2 step 1). OpenCV window only, no pygame.

The forward camera (Pixel / Logitech) shows the room full-screen with a red box on up to 4 objects (YOLO +
ByteTrack from vision/detect_track.py). The eye tracker (built-in camera, its own program) moves a green
cursor. The box under the cursor turns YELLOW and a bar fills; holding your gaze for DWELL_S confirms it
(GREEN). Later the confirmation also needs the EEG (the yellow box flickers, SSVEP must agree).
Confirming only reports the choice, unless --drive is given: then the chair drives to the confirmed object.

    python -m vision.object_select --source 1 --eye-camera 0
Keys: C = re-centre (look at the + first), X = cancel the confirmed object, Q / ESC = quit.
With --drive, for the teammate at the keyboard: SPACE = emergency stop (latched), R = re-arm after it.
The window is full-screen, like the calibration screen, so gaze (0-1 screen coordinates) lines up with it.
"""

from __future__ import annotations

import argparse
import inspect
import logging
import os
import subprocess
import sys
import time
from collections.abc import Sequence
from dataclasses import dataclass, replace

import numpy as np

from control.goto import NavState, nav_step
from control.state_machine import ControlInputs, ControllerState, step
from shared.latest import drain_newest
from shared.protocol import DWELL_S, STALE_INTENT_S, Intent, State, StopRequest, StopSource, Target
from vision.detect_track import (
    DEFAULT_MODEL,
    MAX_TARGETS,
    Track,
    detect,
    focal_length_px,
    load_hfov,
    pick_targets,
    relevant_class_ids,
    separate_targets,
    steering_offset,
)
from vision.destinations import iou
from vision.gaze import GazeSample, pick_region

log = logging.getLogger("vision.object_select")

WINDOW = "look at an object to choose it"
CANVAS_W, CANVAS_H = 1280, 800  # same canvas as the calibration screen, stretched to full screen
MIN_HIT_SIZE = 0.12  # small objects get a gaze target at least 12% of the screen wide and tall
SAME_OBJECT_IOU = 0.3  # a relabelled box overlapping the previous candidate this much is the same object
MIN_ACCURACY = 0.85  # calibration check must reach this before selecting objects (one retry)
MIN_LOOK_S = 0.3  # gaze must rest on a box this long before a clench / key confirms it (no sweep-past picks)
STOP_KEY, REARM_KEY = 32, ord("r")  # SPACE = operator emergency stop, R = re-arm: the same keys as app.py
# control/goto.py's nav_step is gaining an optional `frame_h` keyword (a target whose box is cut off by the bottom
# of the frame counts as arrived). Checked once here, so the drive step works with either version of the planner.
NAV_STEP_TAKES_FRAME_H = "frame_h" in inspect.signature(nav_step).parameters
RED, YELLOW, GREEN, GREY, CURSOR = (0, 0, 255), (0, 220, 255), (0, 220, 0), (160, 160, 160), (255, 120, 0)


@dataclass(frozen=True)
class Selection:
    candidate: int | None = None  # object under the gaze right now
    since: float | None = None  # when the gaze landed on it
    confirmed: int | None = None  # last confirmed object (stays until another is confirmed or X cancels)
    box: tuple[float, float, float, float] | None = None  # candidate's last gaze box (0-1 screen coordinates)
    # The candidate was cancelled (X) or reached: it cannot be confirmed again until the gaze has left it.
    must_look_away: bool = False


def update_selection(sel: Selection, hit: int | None, now: float, dwell_s: float | None = DWELL_S,
                     box: tuple[float, float, float, float] | None = None, confirm: bool = False) -> Selection:
    """Dwell confirmation: same object under the gaze for dwell_s -> confirmed. Looking away restarts the dwell.

    If the tracker relabels the object under the gaze (new ID, box in the same place: overlap >= SAME_OBJECT_IOU),
    it is the same object, so the dwell keeps running instead of restarting.

    An object whose destination was just cleared (must_look_away, see clear_destination) is not confirmed again
    while the gaze stays on it. The gaze leaving it (no box, or a different object) lifts that.
    """
    if hit is None:
        return replace(sel, candidate=None, since=None, box=None, must_look_away=False)
    if hit != sel.candidate:
        same_object = box is not None and sel.box is not None and iou(box, sel.box) >= SAME_OBJECT_IOU
        if same_object:  # still the same object, so must_look_away stays as it is
            confirmed = hit if sel.confirmed == sel.candidate else sel.confirmed
            return replace(sel, candidate=hit, box=box, confirmed=confirmed)
        return replace(sel, candidate=hit, since=now, box=box, must_look_away=False)
    sel = replace(sel, box=box if box is not None else sel.box)
    if sel.must_look_away:
        return replace(sel, since=now)  # dwell clock held at zero: no progress bar, no "CLENCH to confirm"
    looked = now - sel.since
    # Confirm by a clench/key (after a short look), or by dwell alone when dwell_s is set (dwell mode).
    if (confirm and looked >= MIN_LOOK_S) or (dwell_s is not None and looked >= dwell_s):
        return replace(sel, confirmed=hit)
    return sel


def clear_destination(sel: Selection) -> Selection:
    """No destination any more: X was pressed, or the chair arrived.

    Whatever is under the gaze right now cannot be confirmed again until the gaze has left it and come back.
    Without this, in dwell mode, a rider who is still looking at the object confirms it again in the same loop
    pass (the dwell time is already over), so X did nothing and an arrival was reported on every pass.
    """
    return replace(sel, confirmed=None, must_look_away=sel.candidate is not None)


def drive_intent(sel: Selection, hit: int | None, targets: list[Track]) -> Target:
    """Hold-to-move (decision D1) for object mode: FWD only while the rider keeps looking at the CONFIRMED object
    and it is still in view. Looking away, losing the object, or no confirmation -> NONE -> the chair stops."""
    visible = any(t.id == sel.confirmed for t in targets)
    return Target.FWD if sel.confirmed is not None and visible and hit == sel.confirmed else Target.NONE


def gaze_problem(sample: GazeSample | None, now: float) -> str | None:
    """Why there is no usable gaze right now (for the summary), or None if gaze is fine."""
    if sample is None:
        return "no_sample"
    if now - sample.t > STALE_INTENT_S:
        return "stale"
    if sample.point is not None:
        return None
    return "eyes_closed" if sample.closed else "no_face"


CONFIRM_KEY = ord("j")  # "J for jaw": stand-in for a clench. Not SPACE, which is EMERGENCY STOP in app.py.


def confirm_settings(mode: str) -> float | None:
    """Dwell time that confirms by itself: DWELL_S in 'dwell' mode, None when only a clench / key may confirm."""
    return DWELL_S if mode == "dwell" else None


def confirm_event(mode: str, key: int, jaw) -> bool:
    """Did the rider confirm this frame? 'key': J pressed. 'jaw': a clench from the headset (on the practice
    board, J injects a fake clench into the real detector instead)."""
    if mode == "key":
        return key == CONFIRM_KEY
    if mode == "jaw" and jaw is not None:
        if key == CONFIRM_KEY and jaw.mode == "synthetic":
            jaw.inject_fake_clench()
        return jaw.take()
    return False


def dwell_fraction(sel: Selection, now: float, dwell_s: float = DWELL_S) -> float:
    return 0.0 if sel.since is None else min(1.0, (now - sel.since) / dwell_s)


def hit_boxes(targets: list[Track], frame_w: int, frame_h: int,
              min_size: float = MIN_HIT_SIZE) -> dict[int, tuple[float, float, float, float]]:
    """Each target's gaze area in 0-1 screen coordinates. Small objects are enlarged around their centre to at
    least min_size (webcam gaze is only accurate to a few degrees), shifted to stay on screen."""
    boxes = {}
    for t in targets:
        x1, y1, x2, y2 = t.bbox[0] / frame_w, t.bbox[1] / frame_h, t.bbox[2] / frame_w, t.bbox[3] / frame_h
        w, h = max(x2 - x1, min_size), max(y2 - y1, min_size)
        cx = min(max((x1 + x2) / 2, w / 2), 1 - w / 2)
        cy = min(max((y1 + y2) / 2, h / 2), 1 - h / 2)
        boxes[t.id] = (cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)
    return boxes


def corrected_point(sample: GazeSample | None, offset: tuple[float, float], now: float) -> tuple[float, float] | None:
    """Fresh gaze point plus the re-centring offset, or None if there is no usable fresh gaze."""
    if sample is None or sample.point is None or now - sample.t > STALE_INTENT_S:
        return None
    return (min(1.0, max(0.0, sample.point[0] + offset[0])), min(1.0, max(0.0, sample.point[1] + offset[1])))


def status_line(confirm_mode: str, has_gaze: bool, frame_age_s: float, must_look_away: bool, driving: bool) -> str:
    """Text at the bottom of the screen, most urgent first: a frozen camera, then no gaze, then what to do next."""
    if frame_age_s > STALE_INTENT_S:
        return f"CAMERA FROZEN (no new picture for {frame_age_s:.1f} s)"
    if not has_gaze:
        return "NO GAZE (face not seen / eyes closed)"
    keys = ("SPACE stop  R re-arm  " if driving else "") + "C re-centre  X cancel  Q quit"
    if must_look_away:
        return f"look away, then back, to choose this object again  |  {keys}"
    how = {"dwell": "look for 1.5 s", "key": "look, then press J", "jaw": "look, then CLENCH"}[confirm_mode]
    return f"{how} to confirm  |  {keys}"


def draw(cv2, frame: np.ndarray, targets: list[Track], boxes: dict, sel: Selection, point, now: float,
         status: str, dwell_s: float | None = DWELL_S) -> np.ndarray:
    canvas = cv2.resize(frame, (CANVAS_W, CANVAS_H))
    for t in targets:
        x1, y1, x2, y2 = (int(v * s) for v, s in zip(boxes[t.id], (CANVAS_W, CANVAS_H, CANVAS_W, CANVAS_H)))
        color = GREEN if t.id == sel.confirmed else YELLOW if t.id == sel.candidate else RED
        cv2.rectangle(canvas, (x1, y1), (x2, y2), color, 6 if color != RED else 3)
        dist = "" if t.distance_m is None else f" ~{t.distance_m:.1f} m"
        cv2.putText(canvas, f"{t.label}{dist}", (x1 + 6, max(24, y1 + 28)), cv2.FONT_HERSHEY_SIMPLEX, 0.8, color, 2)
        if t.id == sel.candidate and t.id != sel.confirmed:
            if dwell_s is not None:  # dwell mode: progress bar
                cv2.rectangle(canvas, (x1, y2 + 6), (x1 + int((x2 - x1) * dwell_fraction(sel, now, dwell_s)), y2 + 18),
                              YELLOW, -1)
            elif sel.since is not None and now - sel.since >= MIN_LOOK_S:  # clench mode: ready
                cv2.putText(canvas, "CLENCH to confirm", (x1 + 6, y2 + 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, YELLOW, 2)
    cx, cy = CANVAS_W // 2, CANVAS_H // 2
    cv2.line(canvas, (cx - 15, cy), (cx + 15, cy), GREY, 2)
    cv2.line(canvas, (cx, cy - 15), (cx, cy + 15), GREY, 2)
    if point is not None:
        cv2.circle(canvas, (int(point[0] * CANVAS_W), int(point[1] * CANVAS_H)), 14, CURSOR, -1)
    cv2.putText(canvas, status, (12, CANVAS_H - 16), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
    return canvas


def run(cv2, reader, model, classes, gaze_queue, hfov: float, device: str, seconds: float | None,
        tracker_alive=lambda: True, confirm_mode: str = "dwell", jaw=None, driver=None) -> list[str]:
    dwell_s = confirm_settings(confirm_mode)
    ctrl, nav, drive_note = ControllerState(), NavState(), ""
    sel, offset, sample, hit = Selection(), (0.0, 0.0), None, None
    first_seen: dict[int, float] = {}
    tracks: list[Track] = []  # every object YOLO tracks in the newest frame: the planner's obstacles
    targets: list[Track] = []  # the few of them shown as boxes: what the rider can choose
    frame, last_t, confirmations = None, None, []
    gaze_frames = total_frames = 0
    problems: dict[str | None, int] = {}
    start = time.monotonic()
    while seconds is None or time.monotonic() - start < seconds:
        key = cv2.waitKey(1) & 0xFF
        if key in (27, ord("q")):
            break
        if not tracker_alive():  # a live test once ran 4 minutes with a dead tracker: stop and say so
            log.error("eye tracker stopped (see its error above): no gaze possible, ending the session")
            break
        if jaw is not None and not jaw.alive():  # the headset reader crashed: a clench could never confirm now
            log.error("jaw confirm source died (%s): ending the session", jaw.error)
            break
        now = time.monotonic()
        snapshot = reader.latest()
        if snapshot is not None and snapshot[1] != last_t:  # new camera frame: run YOLO + tracking once
            frame, last_t = snapshot
            tracks = detect(model, frame, focal_length_px(frame.shape[1], hfov), device, classes)
            first_seen = {**{t.id: now for t in tracks if t.id not in first_seen}, **first_seen}
            targets = separate_targets(pick_targets(tracks, first_seen, max_n=len(tracks)), frame.shape[1], MAX_TARGETS)
        if frame is None:
            continue
        sample = drain_newest(gaze_queue, sample)
        if key == ord("c") and sample is not None and sample.point is not None:
            offset = (0.5 - sample.point[0], 0.5 - sample.point[1])  # rider is looking at the "+"
            log.info("re-centred: offset %.3f, %.3f", *offset)
        if key == ord("x"):
            sel = clear_destination(sel)
        point = corrected_point(sample, offset, now)
        boxes = hit_boxes(targets, frame.shape[1], frame.shape[0])
        hit = pick_region(point, boxes, hit) if point is not None else None
        before = sel.confirmed
        sel = update_selection(sel, hit, now, box=boxes.get(hit) if hit is not None else None, dwell_s=dwell_s,
                               confirm=confirm_event(confirm_mode, key, jaw))
        problem = gaze_problem(sample, now)
        problems[problem] = problems.get(problem, 0) + 1
        if sel.confirmed is not None and sel.confirmed != before:
            chosen = next(t for t in targets if t.id == sel.confirmed)
            dist = "?" if chosen.distance_m is None else f"~{chosen.distance_m:.1f} m"
            how = {"dwell": "dwell", "key": "J key", "jaw": "jaw clench"}[confirm_mode]
            line = (f"CONFIRMED {chosen.label} #{chosen.id} {dist} steer "
                    f"{steering_offset(chosen.bbox, frame.shape[1]):+.2f} (by {how})")
            log.info(line)
            confirmations.append(line)
        if driver is not None:
            # SPACE -> a StopRequest for the state machine (latched E_STOP), R -> re-arm, exactly as in app.py.
            stops = (StopRequest(StopSource.OPERATOR, now),) if key == STOP_KEY else ()
            sel, ctrl, nav, drive_note = drive_tick(sel, hit, targets, frame.shape[1], hfov, driver, ctrl, nav, now,
                                                    confirmations, obstacles=tracks, frame_h=frame.shape[0],
                                                    frame_t=last_t, stop_requests=stops, rearm=key == REARM_KEY)
        total_frames += 1
        gaze_frames += point is not None
        # last_t is when the newest camera frame arrived; a frozen camera keeps returning that same old frame.
        status = status_line(confirm_mode, point is not None, now - last_t, sel.must_look_away,
                             driver is not None) + drive_note
        cv2.imshow(WINDOW, draw(cv2, frame, targets, boxes, sel, point, now, status, dwell_s))
    log.info("gaze available in %.0f%% of frames", 100 * gaze_frames / max(total_frames, 1))
    lost = ", ".join(f"{name}={100 * n / max(total_frames, 1):.0f}%" for name, n in problems.items() if name)
    log.info("gaze lost because: %s", lost or "never lost")
    return confirmations


def drive_tick(sel: Selection, hit, targets: list[Track], frame_w: int, hfov: float, driver, ctrl: ControllerState,
               nav: NavState, now: float, log_lines: list[str], *, obstacles: Sequence[Track], frame_h: int,
               frame_t: float, stop_requests: tuple[StopRequest, ...] = (), rearm: bool = False):
    """One drive step: planner proposes wheel speeds toward the confirmed object, the safety state machine decides
    whether the chair may move (hold-to-move, 1.5 s hold, obstacle block, stop by default), the driver sends it.

    targets = the boxes the rider can choose; obstacles = EVERY tracked object (the planner skips the target
    itself). frame_t = when the camera frame all of this was computed from arrived. stop_requests / rearm = the
    operator's SPACE / R keys for this step.
    """
    target = next((t for t in targets if t.id == sel.confirmed), None)
    wheels = (0, 0)
    if target is not None:
        extra = {"frame_h": frame_h} if NAV_STEP_TAKES_FRAME_H else {}
        nav, wheels, arrived = nav_step(nav, target, obstacles, frame_w, hfov, driver.distance_cm(), **extra)
        if arrived:
            line = f"ARRIVED at {target.label} #{target.id}"
            log.info(line)
            log_lines.append(line)
            # Arrived = no destination, and the object just reached must be looked away from before it can be
            # chosen again. So the arrival is reported once and the chair stays stopped until a new choice.
            sel, nav, wheels = clear_destination(sel), NavState(), (0, 0)
    else:
        nav = NavState()
    intent_target = drive_intent(sel, hit, targets)
    # The Intent carries the time of the camera FRAME, not the time of this loop pass. A frozen camera keeps
    # handing back its last frame; stamped with `now` it would look fresh forever. Stamped with the frame's own
    # arrival time, the state machine's stale rule (older than STALE_INTENT_S -> STOPPED) stops the chair.
    # The MotorCommand below is still stamped `now`: the driver ignores commands that are themselves old.
    inputs = ControlInputs(intent=Intent(intent_target, 1.0 if intent_target != Target.NONE else 0.0, t=frame_t),
                           stop_requests=stop_requests, rearm=rearm, distance_cm=driver.distance_cm())
    before = ctrl.state
    ctrl, command, _ = step(ctrl, inputs, now, mapping=lambda _target: wheels)
    driver.send(command)
    if ctrl.state != before:
        log.info("state %s -> %s", before.value, ctrl.state.value)
    note = f"  |  {ctrl.state.value}" + ("" if command.stop else f" wheels {command.left},{command.right}")
    if ctrl.state == State.E_STOP:  # latched: only the operator's R key releases it
        note += " (emergency stop: press R to re-arm)"
    return sel, ctrl, nav, note


def show_text(cv2, text: str) -> None:
    """Full-screen instruction (used during the jaw calibration)."""
    canvas = np.zeros((CANVAS_H, CANVAS_W, 3), np.uint8)
    cv2.putText(canvas, text, (60, CANVAS_H // 2), cv2.FONT_HERSHEY_SIMPLEX, 1.4, (255, 255, 255), 3)
    cv2.imshow(WINDOW, canvas)
    cv2.waitKey(1)


def start_jaw(cv2, args):
    """Connect the headset, run the on-screen jaw calibration, start the clench detector. None on failure."""
    from bci.jaw_live import JawConfirmSource, parse_channels

    try:
        jaw = JawConfirmSource(args.jaw_board, args.jaw_port, channels=parse_channels(args.jaw_channels))
    except Exception:
        log.exception("could not connect to the OpenBCI board (%s)", args.jaw_board)
        return None
    try:
        threshold = jaw.calibrate(lambda text: show_text(cv2, text))
    except ValueError as error:
        log.error("jaw calibration failed: %s", error)
        show_text(cv2, "Jaw calibration failed: check electrodes")
        jaw.stop()
        return None
    log.info("jaw calibrated (threshold %.1f)", threshold)
    jaw.start()
    return jaw


def calibrate_now(cv2, eye_camera: int, out: str) -> bool:
    """Calibrate in the rider's CURRENT position: a calibration from another seat or posture drifted by up to
    0.45 of the screen in a live test. Retries once below MIN_ACCURACY; returns False only if cancelled."""
    from vision.gaze_calibrate import run_calibration
    from vision.gaze_tracker import FaceLandmarkSource

    source = FaceLandmarkSource(eye_camera)
    try:
        for attempt in (1, 2):
            accuracy = run_calibration(cv2, source, out)
            if accuracy is None:
                return False
            if accuracy >= MIN_ACCURACY:
                return True
            log.warning("calibration accuracy %.0f%% < %.0f%% (attempt %d): sit still, head level, retrying",
                        100 * accuracy, 100 * MIN_ACCURACY, attempt)
        log.warning("continuing with the lower-accuracy calibration; expect more re-centring")
        return True
    finally:
        source.close()  # free the camera for the tracker program
        cv2.destroyAllWindows()


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="Choose a real object by looking at it.")
    parser.add_argument("--source", default="auto", help="forward camera index/URL, or auto (= not the face camera)")
    parser.add_argument("--eye-camera", default="auto", help="camera that sees the rider's face, or auto")
    parser.add_argument("--calibration", default="data/raw/gaze_calibration.json")
    parser.add_argument("--hfov", type=float, default=load_hfov(), help="calibrated if data/raw/camera_calibration.json exists")
    parser.add_argument("--device", default="mps")
    parser.add_argument("--seconds", type=float, default=None)
    parser.add_argument("--confirm", choices=["dwell", "key", "jaw"], default="dwell",
                        help="dwell = look 1.5 s; key = look + J; jaw = look + jaw clench (OpenBCI)")
    parser.add_argument("--jaw-board", choices=["synthetic", "wifi", "dongle"], default="dongle",
                        help="--confirm jaw: synthetic = practice (J injects a fake clench)")
    parser.add_argument("--jaw-port", default=None, help="OpenBCI dongle port, e.g. /dev/cu.usbserial-DM0xxxxx")
    parser.add_argument("--jaw-channels", default="1", help="Cyton channels with an electrode, e.g. 1 or 1,2")
    parser.add_argument("--drive", action="store_true", help="drive to the confirmed object (needs --mock or --serial)")
    port = parser.add_mutually_exclusive_group()
    port.add_argument("--mock", action="store_true", help="--drive into a fake serial port (no hardware)")
    port.add_argument("--serial", metavar="PORT", help="--drive: ESP32 bridge port (HUMANS ONLY, wheels up first)")
    parser.add_argument("--skip-calibration", action="store_true",
                        help="reuse the saved calibration (only if you have not moved since)")
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    from vision.gaze_link import calibrate_eyetrax, calibration_hint, calibration_ready, gaze_backend

    backend = gaze_backend()
    if args.skip_calibration and not calibration_ready(backend, args.calibration):
        log.error("no gaze calibration for the %s tracker: run `%s` first", backend, calibration_hint(backend))
        return 2
    if args.drive and not (args.mock or args.serial):
        log.error("--drive needs --mock (no hardware) or --serial PORT")
        return 2
    if args.serial:
        from motors.driver import looks_like_openbci_dongle

        if looks_like_openbci_dongle(args.serial):
            log.error("%s looks like the OpenBCI dongle, not the ESP32: refusing to send motor commands", args.serial)
            return 2
    import cv2
    from ultralytics import YOLO

    from vision.camera_source import LatestFrameReader, open_capture, parse_source
    from vision.gaze_link import start_gaze_tracker

    if "auto" in (args.source, args.eye_camera):
        from vision.camera_roles import assign_roles, probe_cameras

        probes = probe_cameras()
        log.info("cameras: %s", ", ".join(f"{p.index}{' (face)' if p.sees_face else ''}" for p in probes))
        try:
            eye, forward = assign_roles(probes)
        except RuntimeError as error:
            log.error("%s", error)
            return 2
        args.eye_camera = eye if args.eye_camera == "auto" else int(args.eye_camera)
        args.source = str(forward) if args.source == "auto" else args.source
        log.info("eye camera = %s, forward camera = %s", args.eye_camera, args.source)
    if not args.skip_calibration:  # calibrate in the rider's CURRENT seat (an old calibration drifted badly)
        ok = (calibrate_eyetrax(args.eye_camera) if backend == "eyetrax"
              else calibrate_now(cv2, int(args.eye_camera), args.calibration))
        if not ok:
            return 1
    reader = LatestFrameReader(parse_source(args.source), opener=open_capture)
    reader.start()
    process, gaze_queue, gaze_stop = start_gaze_tracker(int(args.eye_camera), args.calibration, backend)
    model = YOLO(DEFAULT_MODEL)
    cv2.namedWindow(WINDOW, cv2.WINDOW_NORMAL)
    cv2.setWindowProperty(WINDOW, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)
    jaw, driver = None, None
    if args.drive:
        from motors.driver import MotorDriver, open_serial
        from motors.mock_serial import MockSerial

        mock = MockSerial() if args.mock else None
        driver = MotorDriver((lambda: mock) if mock else (lambda: open_serial(args.serial)))
        driver.start()  # streams STOP lines from now on
    try:
        if args.confirm == "jaw":
            jaw = start_jaw(cv2, args)
            if jaw is None:
                return 2
        confirmations = run(cv2, reader, model, relevant_class_ids(model.names), gaze_queue, args.hfov, args.device,
                            args.seconds, tracker_alive=lambda: process.poll() is None, confirm_mode=args.confirm,
                            jaw=jaw, driver=driver)
    finally:
        if driver is not None:
            driver.stop()  # final explicit STOP lines
        if jaw is not None:
            jaw.stop()
        gaze_stop.set()
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
        reader.stop()
        cv2.destroyAllWindows()
    print(f"summary: confirmations={len(confirmations)}")
    for line in confirmations:
        print("  " + line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
