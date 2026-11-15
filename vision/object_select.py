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
import math
import os
import subprocess
import sys
import time
from collections.abc import Sequence
from dataclasses import dataclass, replace

import numpy as np

from control.astar import astar_path
from control.follow import follow_step
from control.goto import NavState, nav_step
from control.navigation import goal_from_target, to_wheels
from control.state_machine import ControlInputs, ControllerState, step
from shared.latest import drain_newest
from shared.protocol import DWELL_S, STALE_INTENT_S, Intent, MotorCommand, State, StopRequest, StopSource, Target
from vision.detect_track import (
    DEFAULT_MODEL,
    SEG_MODEL,
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
from interface import screens, window
from vision import hud
from vision.chevrons import route_length_m
from vision.manual_arrows import ARROW_NAMES, ARROW_WHEELS, arrow_at, draw_arrows
from vision.scene_worker import SceneWorker
from vision.smoothing import EuroState, glide_tracks, one_euro
from vision.floor_route import Route
from vision.route_scene import (
    CAM_HEIGHT_M,
    CAM_PITCH_DEG,
    RIBBON_DISPLAY_SCALE,
    floor_metres,
    floor_view,
    plan,
)
from vision.destinations import iou
from vision.gaze import GazeSample, pick_region

log = logging.getLogger("vision.object_select")

WINDOW = "look at an object to choose it"
CANVAS_W, CANVAS_H = 1280, 800  # same canvas as the calibration screen, stretched to full screen
VIEW_H = CANVAS_H - hud.TOP_BAR_H - hud.BOTTOM_BAR_H  # height left for the camera picture between the two bars
MIN_HIT_SIZE = 0.12  # small objects get a gaze target at least 12% of the screen wide and tall
SAME_OBJECT_IOU = 0.3  # a relabelled box overlapping the previous candidate this much is the same object
MIN_ACCURACY = 0.85  # calibration check must reach this before selecting objects (one retry)
MIN_LOOK_S = 0.3  # gaze must rest on a box this long before a clench / key confirms it (no sweep-past picks)
# Look for objects this often. Furniture does not move and the chair is slow, so 7 times a second is plenty,
# and well inside the 0.5 s limit after which a camera frame counts as stale.
DETECT_PERIOD_S = 0.15
SESSION_LOG_DIR = "data/raw/sessions"  # one log file per run (data/raw is gitignored)
JAW_METER_BLOCKS = 10  # status-bar clench meter: all blocks lit = at the rider's threshold
ROUTE_RADIUS_M = 0.4  # planner keeps this much space around every obstacle: chair half-width 0.3 m + 0.1 m margin
OBSTACLE_SAMPLE_M = 0.2  # obstacle points this far apart across an object (less than 2 x ROUTE_RADIUS_M: no gaps)
OBSTACLE_DEPTH_M = 0.4  # an object is treated as this deep (a second row of points behind its front)
STOP_BEFORE_TARGET_M = 0.4  # the route ends this far before the target's estimated position
STOP_KEY, REARM_KEY = 32, ord("r")  # SPACE = operator emergency stop, R = re-arm: the same keys as app.py
# In key mode (no headset) SPACE confirms instead, so the emergency stop moves to S. See stop_key().
KEY_MODE_STOP_KEY = ord("s")
BLINK_MIN_S, BLINK_MAX_CONFIRM_S = 0.05, 0.4  # a deliberate blink: eyes closed this long
DOUBLE_BLINK_GAP_S = 0.7  # the second blink must end within this time of the first
CANCEL_BLINKS = 3  # this many short blinks within BLINK_SERIES_S cancel the drive (rider changed their mind)
BLINK_SERIES_S = 1.5
PLAN_LOG_EVERY_S = 1.0  # the route in words and the wheel command go to the log this often
PLAN_SPEED_MPS = 0.4  # the planner's top speed (NavConfig.max_speed), for the time estimate
SWITCH_MARGIN = 0.05  # gaze must be this much nearer (fraction of the picture) to switch objects
MAX_GAZE_DISTANCE = 0.25  # gaze farther than this from every object highlights nothing
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




@dataclass(frozen=True)
class DestinationMemory:
    """The confirmed object as last detected, and the route planned to it then."""
    track: Track | None = None
    route: object = None
    route_m: np.ndarray | None = None
    seen_t: float = -math.inf  # frame time of that detection


def hold_destination(mem: DestinationMemory, targets: list[Track], route, route_m, confirmed: int | None,
                     frame_t: float):
    """Keep driving to the confirmed object when detection or planning drops it. Returns (memory, targets, route,
    route_m, held). Seen -> remembered. Not seen -> its last box and route are put back (held=True). A frame with
    no route -> the last route. No destination -> nothing remembered."""
    if confirmed is None:
        return DestinationMemory(), targets, route, route_m, False
    current = next((t for t in targets if t.id == confirmed), None)
    known = mem.track is not None and mem.track.id == confirmed
    if current is not None:
        if route_m is None and known and mem.route_m is not None:  # no route this frame: keep the last one
            route, route_m = mem.route, mem.route_m
        return DestinationMemory(current, route, route_m, frame_t), targets, route, route_m, False
    if not known:
        return mem, targets, route, route_m, False
    return mem, [*targets, mem.track], mem.route, mem.route_m, True  # out of sight: keep its last box and route


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


CONFIRM_KEY = ord("j")  # "J for jaw": stand-in for a clench.
SPACE = 32  # in key mode SPACE also confirms (Prakhar, Sun Nov 15: no headset for now, SPACE to confirm)


@dataclass(frozen=True)
class BlinkConfirm:
    """State of the double-blink detector (confirm mode "blink")."""
    closed_since: float | None = None  # when the eyes closed, None while open
    last_blink_end: float | None = None  # end of the previous short blink


def double_blink(state: BlinkConfirm, closed: bool, t: float) -> tuple[BlinkConfirm, bool]:
    """Feed one NEW gaze sample (eyes closed?, its time). True when a second short blink ends within
    DOUBLE_BLINK_GAP_S of the first. A blink counts only if the eyes were closed BLINK_MIN_S..BLINK_MAX_CONFIRM_S:
    shorter is a tracker flicker, longer is resting the eyes (which also stops the chair: no gaze)."""
    if closed:
        return (state if state.closed_since is not None else replace(state, closed_since=t)), False
    if state.closed_since is None:
        return state, False
    length = t - state.closed_since
    if not BLINK_MIN_S <= length <= BLINK_MAX_CONFIRM_S:
        return BlinkConfirm(), False  # not a deliberate blink: start again
    if state.last_blink_end is not None and t - state.last_blink_end <= DOUBLE_BLINK_GAP_S:
        return BlinkConfirm(), True  # second blink: confirm, and start fresh
    return BlinkConfirm(last_blink_end=t), False


@dataclass(frozen=True)
class BlinkSeries:
    """Recent short blinks, for the triple-blink cancel."""
    closed_since: float | None = None
    ends: tuple[float, ...] = ()  # end times of recent short blinks


def count_blinks(state: BlinkSeries, closed: bool, t: float) -> tuple[BlinkSeries, int]:
    """Feed one NEW gaze sample. Returns how many short blinks ended within BLINK_SERIES_S, counted at the moment a
    blink ends (0 otherwise). After CANCEL_BLINKS the series starts again, so one triple blink acts once."""
    if closed:
        return (state if state.closed_since is not None else replace(state, closed_since=t)), 0
    if state.closed_since is None:
        return state, 0
    length = t - state.closed_since
    if not BLINK_MIN_S <= length <= BLINK_MAX_CONFIRM_S:
        return BlinkSeries(), 0
    ends = tuple(e for e in state.ends if t - e <= BLINK_SERIES_S) + (t,)
    if len(ends) >= CANCEL_BLINKS:
        return BlinkSeries(), len(ends)
    return BlinkSeries(ends=ends), len(ends)


def confirm_settings(mode: str) -> float | None:
    """Dwell time that confirms by itself: DWELL_S in 'dwell' mode, None when only a clench / key may confirm."""
    return DWELL_S if mode == "dwell" else None


def confirm_event(mode: str, key: int, jaw) -> bool:
    """Did the rider confirm this frame? 'key': J pressed. 'jaw': a clench from the headset (on the practice
    board, J injects a fake clench into the real detector instead)."""
    if mode in ("key", "blink"):  # in blink mode SPACE / J still confirm, as a backup
        return key in (CONFIRM_KEY, SPACE)
    if mode == "jaw" and jaw is not None:
        if key == CONFIRM_KEY and jaw.mode == "synthetic":
            jaw.inject_fake_clench()
        fired = jaw.take()
        if fired:  # logged whether or not the gaze is on an object, so a session can be checked afterwards
            log.info("JAW CLENCH detected")
        return fired
    return False


def dwell_fraction(sel: Selection, now: float, dwell_s: float = DWELL_S) -> float:
    return 0.0 if sel.since is None else min(1.0, (now - sel.since) / dwell_s)


def hit_boxes(targets: list[Track], frame_w: int, frame_h: int,
              min_size: float = MIN_HIT_SIZE) -> dict[int, tuple[float, float, float, float]]:
    """Each target's gaze area in 0-1 screen coordinates. Small objects are enlarged around their centre to at
    least min_size (webcam gaze is only accurate to a few degrees), shifted to stay on screen."""
    boxes = {}
    # Smallest first: the gaze test takes the first box it is inside, so an object in front of a bigger one
    # (a chair before a couch) is the one chosen where they overlap; the couch is chosen beside the chair.
    for t in sorted(targets, key=lambda t: (t.bbox[2] - t.bbox[0]) * (t.bbox[3] - t.bbox[1])):
        x1, y1, x2, y2 = t.bbox[0] / frame_w, t.bbox[1] / frame_h, t.bbox[2] / frame_w, t.bbox[3] / frame_h
        w, h = max(x2 - x1, min_size), max(y2 - y1, min_size)
        cx = min(max((x1 + x2) / 2, w / 2), 1 - w / 2)
        cy = min(max((y1 + y2) / 2, h / 2), 1 - h / 2)
        boxes[t.id] = (cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)
    return boxes


def nearest_target(point: tuple[float, float], boxes: dict, current: int | None,
                   switch_margin: float = SWITCH_MARGIN, max_distance: float = MAX_GAZE_DISTANCE) -> int | None:
    """The object nearest to where the eyes point (0-1 picture coordinates), so something is always highlighted
    even when webcam gaze lands a little beside the object. Distance is 0 inside an object's box.

    Calm by design: the highlighted object only changes when another one is clearly nearer (by switch_margin),
    and nothing is chosen when the gaze is far from every object (max_distance), e.g. looking at the sky."""
    if not boxes:
        return None
    def distance(box) -> float:
        x1, y1, x2, y2 = box
        dx = max(x1 - point[0], 0.0, point[0] - x2)
        dy = max(y1 - point[1], 0.0, point[1] - y2)
        return math.hypot(dx, dy)
    distances = {tid: distance(box) for tid, box in boxes.items()}
    best = min(distances, key=distances.get)
    if distances[best] > max_distance:
        return None
    if current in distances and distances[current] <= distances[best] + switch_margin:
        return current  # keep the current one unless another is clearly nearer: no flicker between neighbours
    return best


def corrected_point(sample: GazeSample | None, offset: tuple[float, float], now: float) -> tuple[float, float] | None:
    """Fresh gaze point plus the re-centring offset, or None if there is no usable fresh gaze."""
    if sample is None or sample.point is None or now - sample.t > STALE_INTENT_S:
        return None
    return (min(1.0, max(0.0, sample.point[0] + offset[0])), min(1.0, max(0.0, sample.point[1] + offset[1])))


def stop_key(confirm_mode: str) -> int:
    """The operator's emergency-stop key: SPACE, except in key mode where SPACE confirms and S stops."""
    return KEY_MODE_STOP_KEY if confirm_mode in ("key", "blink") else STOP_KEY


def status_line(confirm_mode: str, has_gaze: bool, frame_age_s: float, must_look_away: bool, driving: bool) -> str:
    """Text at the bottom of the screen, most urgent first: a frozen camera, then no gaze, then what to do next."""
    if not has_gaze:
        return "NO GAZE (face not seen / eyes closed)"
    stop_name = "S" if confirm_mode in ("key", "blink") else "SPACE"
    keys = (f"{stop_name} stop  R re-arm  " if driving else "") + "C re-centre  X cancel  Q quit"
    if must_look_away:
        return f"look away, then back, to choose this object again  |  {keys}"
    how = {"dwell": "look for 1.5 s", "key": "look, then press SPACE", "jaw": "look, then CLENCH",
           "blink": "look, then BLINK TWICE"}[confirm_mode]
    return f"{how} to confirm  |  {keys}"


def route_plan_text(route_m: np.ndarray) -> str:
    """The route in words, leg by leg from the chair: "turn right 23 deg, forward 1.6 m, turn left 10 deg, ..."."""
    path = np.vstack([[0.0, 0.0], np.asarray(route_m, float).reshape(-1, 2)])
    heading, parts, total = 0.0, [], 0.0
    for a, b in zip(path, path[1:]):
        dx, dy = b - a
        length = float(np.hypot(dx, dy))
        if length < 0.05:
            continue
        turn = math.degrees(math.atan2(dy, dx)) - heading
        turn = (turn + 180) % 360 - 180  # the shorter way round
        if abs(turn) >= 5:
            parts.append(f"turn {'left' if turn > 0 else 'right'} {abs(turn):.0f} deg")
        parts.append(f"forward {length:.1f} m")
        heading += turn
        total += length
    return f"{', '.join(parts)} (total {total:.1f} m, about {total / PLAN_SPEED_MPS:.0f} s at {PLAN_SPEED_MPS} m/s)"


def jaw_meter(level: float | None) -> str:
    """Live clench level for the status bar: ten blocks, full at this rider's threshold."""
    if level is None:
        return "JAW: no signal"
    filled = max(0, min(JAW_METER_BLOCKS, round(level * JAW_METER_BLOCKS)))
    return "JAW " + "■" * filled + "□" * (JAW_METER_BLOCKS - filled) + (" CLENCH" if level >= 1.0 else "")


def to_view_point(point: tuple[float, float] | None) -> tuple[float, float] | None:
    """Gaze point as a fraction of the whole screen -> fraction of the camera picture.

    The camera picture no longer fills the screen: it sits between a top bar and a bottom bar. A gaze on
    either bar is on no object, so it gives None (the same as looking away)."""
    if point is None:
        return None
    y = (point[1] * CANVAS_H - hud.TOP_BAR_H) / VIEW_H
    return (point[0], y) if 0.0 <= y <= 1.0 else None


def draw(cv2, frame: np.ndarray, targets: list[Track], boxes: dict, sel: Selection, point, now: float,
         status: str, dwell_s: float | None = DWELL_S, mode: str = "Choose a destination",
         route: Route | None = None, route_m: np.ndarray | None = None,
         camera: tuple[float, float, float] | None = None, arrows: bool = False,
         arrow_active=None) -> np.ndarray:
    """The screen: camera picture with each selectable object outlined, the gaze cursor, and the status bars.
    `point` is the gaze as a fraction of the camera picture (see to_view_point). Returns CANVAS_H x CANVAS_W."""
    view = cv2.resize(frame, (CANVAS_W, VIEW_H))
    sx, sy = CANVAS_W / frame.shape[1], VIEW_H / frame.shape[0]
    objects = []
    for t in targets:
        confirmed, candidate = t.id == sel.confirmed, t.id == sel.candidate
        if confirmed:
            progress = 1.0
        elif candidate and dwell_s is not None:  # dwell mode: the ring fills while the rider keeps looking
            progress = dwell_fraction(sel, now, dwell_s)
        elif candidate:  # clench / key mode: a full ring means "looked long enough, confirm now"
            progress = 1.0 if sel.since is not None and now - sel.since >= MIN_LOOK_S else 0.0
        else:
            progress = 0.0
        x1, y1, x2, y2 = t.bbox
        outline = None if t.outline is None else t.outline * (sx, sy)  # a new array: the track is left alone
        objects.append(hud.SceneObject(t.label, (x1 * sx, y1 * sy, x2 * sx, y2 * sy), outline,
                                       confirmed or candidate, progress, confirmed))
    # The "+" the rider looks at to re-centre (C key) marks the middle of the SCREEN, not of the picture.
    cx, cy = CANVAS_W // 2, CANVAS_H // 2 - hud.TOP_BAR_H
    cv2.line(view, (cx - 15, cy), (cx + 15, cy), GREY, 2)
    cv2.line(view, (cx, cy - 15), (cx, cy + 15), GREY, 2)
    # No cursor on screen (Prakhar, Sun Nov 15: it jumped around and distracted). The gaze only decides which
    # object is highlighted; see nearest_target().
    cursor = None
    # No floating chevrons (Prakhar, Sun Nov 15). The route is still planned and driven; only its length is shown.
    chosen = next((t for t in targets if t.id == sel.confirmed), None)
    label = f"Toward {chosen.label} · {route_length_m(route_m):.1f} m" if route_m is not None and chosen else None
    screen = hud.render(view, hud.HudState(objects=tuple(objects), cursor=cursor, mode=mode, status=status,
                                           guides=(), guide_label=label, clock=now))
    if not arrows:
        return screen
    # Manual gaze arrows at the edges of the camera view; hud colours are RGB, OpenCV wants BGR.
    return draw_arrows(cv2, screen, hud.TOP_BAR_H, VIEW_H, arrow_active, hud.FILL_RGB[::-1], hud.CYAN_RGB[::-1])


def obstacle_points(tracks: list[Track], exclude_id: int | None, frame_w: int, hfov: float) -> np.ndarray:
    """Every detected object except the target -> floor points in metres (forward, left), the chair at (0, 0).

    Points every OBSTACLE_SAMPLE_M across the object's width, at its estimated distance and OBSTACLE_DEPTH_M
    behind it, so even a long couch is a solid wall to the planner (no gaps between sample points)."""
    focal = focal_length_px(frame_w, hfov)
    points = []
    for t in tracks:
        if t.id == exclude_id or t.distance_m is None:
            continue
        x1, _, x2, _ = t.bbox
        width_m = (x2 - x1) / focal * t.distance_m
        count = max(3, math.ceil(width_m / OBSTACLE_SAMPLE_M) + 1)
        for x in np.linspace(x1, x2, count):
            offset = (x - frame_w / 2) / (frame_w / 2)
            for extra in (0.0, OBSTACLE_DEPTH_M):
                points.append(goal_from_target(offset, t.distance_m + extra, hfov))
    return np.array(points, dtype=float).reshape(-1, 2)


def plan_for_drive(frame: np.ndarray, tracks: list[Track], target: Track, hfov: float, cam_h: float,
                   cam_pitch: float) -> tuple[None, np.ndarray | None]:
    """The route to the target in metres in the chair's frame (for the follower and the chevrons), or None.

    Simple and robust on purpose: every detected object becomes a block on a 10 cm floor grid, grown by the
    chair's half-width plus a margin, and A* (control/astar.py) finds the shortest way around them to a stop
    point in front of the target. The same idea as the stereo-camera path planner, with our single camera's
    distance estimates instead of stereo depth. Floor the camera cannot see is assumed open: the ESP32's
    ultrasonic stop is the backstop for anything the detector misses. Any failure gives None (no movement).
    cam_h / cam_pitch are unused here; kept so the caller's signature does not change."""
    try:
        if target.distance_m is None:
            return None, None
        frame_w = frame.shape[1]
        centre = (target.bbox[0] + target.bbox[2]) / 2
        goal = np.array(goal_from_target((centre - frame_w / 2) / (frame_w / 2), target.distance_m, hfov))
        distance = float(np.hypot(*goal))
        if distance <= STOP_BEFORE_TARGET_M:
            return None, None  # already there
        stop = goal * (distance - STOP_BEFORE_TARGET_M) / distance
        path = astar_path(tuple(stop), obstacle_points(tracks, target.id, frame_w, hfov), ROUTE_RADIUS_M)
        if path is None or len(path) < 2:
            return None, None
        return None, np.array(path[1:], dtype=float)  # path[0] is the chair itself
    except Exception:
        log.exception("route planning failed: no route, the chair stays stopped")
        return None, None


def run(cv2, reader, model, classes, gaze_queue, hfov: float, device: str, seconds: float | None,
        tracker_alive=lambda: True, confirm_mode: str = "dwell", jaw=None, driver=None,
        follow: str = "direct", cam_h: float = CAM_HEIGHT_M, cam_pitch: float = CAM_PITCH_DEG) -> list[str]:
    """follow = "direct": the planner steers straight at the object (control/goto.py). follow = "route": the
    chair follows the shortest safe route planned on the floor in each camera frame (control/follow.py)."""
    dwell_s = confirm_settings(confirm_mode)
    ctrl, nav, drive_note = ControllerState(), NavState(), ""
    route, route_m = None, None  # newest route to the destination (image pixels, metres), from the worker
    planned_for = None  # the destination the worker's newest result was planned for
    memory = DestinationMemory()  # the confirmed object as last seen, for short detection dropouts
    sel, offset, sample, hit = Selection(), (0.0, 0.0), None, None
    blink_state = BlinkConfirm()
    series = BlinkSeries()
    last_plan_log = -math.inf
    shown = None  # newest camera picture, for the screen only
    gaze_filter, drawn_tracks = EuroState(), {}  # smoothing state: cursor filter, outlines as drawn last time
    tracks: list[Track] = []  # every object YOLO tracks in the newest frame: the planner's obstacles
    targets: list[Track] = []  # the few of them shown as boxes: what the rider can choose
    frame, last_t, confirmations = None, None, []
    gaze_frames = total_frames = 0
    problems: dict[str | None, int] = {}
    def detect_frame(picture):  # runs on the worker thread
        return detect(model, picture, focal_length_px(picture.shape[1], hfov), device, classes)

    def plan_frame(picture, all_tracks, target):  # runs on the worker thread
        return plan_for_drive(picture, all_tracks, target, hfov, cam_h, cam_pitch)

    # Detection and route planning run on their own thread, so the screen and the gaze cursor never wait for them.
    worker = SceneWorker(reader, detect_frame, plan_frame if follow == "route" else None, DETECT_PERIOD_S)
    worker.start()
    try:
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
            if not worker.alive():  # detection thread crashed: no new detections, so nothing can be chosen or driven
                log.error("detection thread died (%s): ending the session", worker.error)
                break
            now = time.monotonic()
            snapshot = reader.latest()
            if snapshot is not None:
                shown = snapshot[0]  # the picture on screen follows the camera every pass; outlines use the last detection
            # Newest finished detection (and route) from the worker thread. replanned = it is new this pass.
            replanned, scene = False, worker.latest()
            if scene is not None and scene.frame_t != last_t:
                replanned = True
                frame, last_t, tracks, targets = scene.frame, scene.frame_t, scene.tracks, scene.targets
                planned_for = scene.destination
                # A route planned for an earlier destination is not this destination's route.
                route, route_m = (scene.route, scene.route_m) if scene.destination == sel.confirmed else (None, None)
                memory, targets, route, route_m, held = hold_destination(memory, targets, route, route_m,
                                                                         sel.confirmed, last_t)
                if held:
                    planned_for = sel.confirmed  # the remembered route was planned for this destination
            if frame is None:
                continue
            before_sample = sample
            sample = drain_newest(gaze_queue, sample)
            blinked = tripled = False
            if sample is not None and sample is not before_sample:
                if confirm_mode == "blink":
                    blink_state, blinked = double_blink(blink_state, sample.closed, sample.t)
                    if blinked:
                        log.info("DOUBLE BLINK detected")
                series, count = count_blinks(series, sample.closed, sample.t)
                tripled = count >= CANCEL_BLINKS
            if key == ord("c") and sample is not None and sample.point is not None:
                offset = (0.5 - sample.point[0], 0.5 - sample.point[1])  # rider is looking at the "+"
                log.info("re-centred: offset %.3f, %.3f", *offset)
            if key == ord("x"):
                sel = clear_destination(sel)
            gaze_filter, point = one_euro(gaze_filter, corrected_point(sample, offset, now), now)  # steadied gaze
            view_point = to_view_point(point)  # ... and of the camera picture (None when looking at a bar)
            boxes = hit_boxes(targets, frame.shape[1], frame.shape[0])
            # LOCKED = a destination is confirmed and the chair drives there. The gaze no longer chooses anything
            # (other objects are hidden), the chair keeps going while the destination is in view, and only a
            # TRIPLE BLINK, X or S ends it early. Arrival unlocks by itself (drive_tick clears the destination).
            locked = driver is not None and sel.confirmed is not None
            if locked and tripled:
                log.info("TRIPLE BLINK: destination cancelled, chair stopped, choosing again")
                sel, locked = clear_destination(sel), False
            if locked:
                hit = sel.confirmed if any(t.id == sel.confirmed for t in targets) else None
            else:
                hit = nearest_target(view_point, boxes, hit) if view_point is not None else None
            # Manual arrows: only while no destination is locked. Looking at one drives at once (no confirm).
            arrow = arrow_at(view_point) if driver is not None and not locked else None
            if arrow is not None:
                hit = None  # an arrow, not an object: nothing to highlight or confirm
            before = sel.confirmed
            confirm = (confirm_event(confirm_mode, key, jaw) or blinked) and not locked
            if confirm:  # say what the confirm landed on, so a "nothing happened" can be explained from the log
                looked = None if sel.since is None or hit != sel.candidate else now - sel.since
                log.info("CONFIRM pressed: gaze on %s%s", "nothing (cursor not on an object)" if hit is None else
                         f"object #{hit}", "" if looked is None else f" for {looked:.1f} s (needs {MIN_LOOK_S} s)")
            if not locked:
                sel = update_selection(sel, hit, now, box=boxes.get(hit) if hit is not None else None,
                                       dwell_s=dwell_s, confirm=confirm)
            problem = gaze_problem(sample, now)
            problems[problem] = problems.get(problem, 0) + 1
            if sel.confirmed is not None and sel.confirmed != before:
                chosen = next(t for t in targets if t.id == sel.confirmed)
                dist = "?" if chosen.distance_m is None else f"~{chosen.distance_m:.1f} m"
                how = {"dwell": "dwell", "key": "SPACE key", "jaw": "jaw clench", "blink": "double blink"}[confirm_mode]
                line = (f"CONFIRMED {chosen.label} #{chosen.id} {dist} steer "
                        f"{steering_offset(chosen.bbox, frame.shape[1]):+.2f} (by {how})")
                log.info(line)
                confirmations.append(line)
            worker.set_destination(sel.confirmed if follow == "route" else None)  # plan for it from the next frame
            if driver is not None:
                # SPACE -> a StopRequest for the state machine (latched E_STOP), R -> re-arm, exactly as in app.py.
                stops = (StopRequest(StopSource.OPERATOR, now),) if key == stop_key(confirm_mode) else ()
                if arrow is not None and not stops:
                    ctrl, drive_note = manual_tick(arrow, driver, ctrl, now)
                else:
                    sel, ctrl, nav, drive_note = drive_tick(sel, hit, targets, frame.shape[1], hfov, driver, ctrl, nav, now,
                                                        confirmations, obstacles=tracks, frame_h=frame.shape[0],
                                                        frame_t=last_t, stop_requests=stops, rearm=key == REARM_KEY,
                                                        follow=follow, route_m=route_m, replan=replanned,
                                                    route_pending=planned_for != sel.confirmed)
                if follow == "route" and now - last_plan_log >= PLAN_LOG_EVERY_S:
                    last_plan_log = now  # once a second: the plan and what the wheels are being told, in words
                    log.info("PLAN %s | sending: %s", route_plan_text(route_m) if route_m is not None else
                             ("no route yet" if sel.confirmed is not None else "no destination"), drive_note.strip(" |"))
            total_frames += 1
            gaze_frames += point is not None
            # last_t is when the newest camera frame arrived; a frozen camera keeps returning that same old frame.
            status = status_line(confirm_mode, point is not None, now - last_t, sel.must_look_away, driver is not None)
            if drive_note:  # chair state first: the bar cuts long text off at the right, and the key hints can go
                status = drive_note.strip(" |") + "  |  " + status
            chosen = next((t for t in targets if t.id == sel.confirmed), None)
            if chosen is not None and driver is not None:
                status = (f"DRIVING TO {chosen.label}  |  "
                          f"{drive_note.strip(' |')}  |  "
                          f"triple-blink or {'S' if confirm_mode in ('key', 'blink') else 'SPACE'} to stop  X cancel")
            elif chosen is not None:
                status = f"DESTINATION: {chosen.label}  |  " + status
            if confirm_mode == "jaw" and jaw is not None:
                status = jaw_meter(jaw.level()) + "  |  " + status
            mode = "Drive to object" if driver is not None else "Choose a destination"
            screen_frame = shown if shown is not None and shown.shape == frame.shape else frame
            drawn_tracks = glide_tracks(drawn_tracks, targets)  # outlines glide between detections instead of jumping
            drawn_targets = [drawn_tracks[t.id] for t in targets
                             if driver is None or sel.confirmed is None or t.id == sel.confirmed]  # locked: only it
            window.show(cv2, WINDOW, draw(cv2, screen_frame, drawn_targets, boxes, sel, view_point, now, status, dwell_s, mode,
                                    route, route_m, (hfov, cam_h, cam_pitch),
                                    arrows=driver is not None and sel.confirmed is None, arrow_active=arrow))
        elapsed = max(time.monotonic() - start, 1e-6)
        log.info("screen ran at %.0f fps (%d passes in %.0f s)", total_frames / elapsed, total_frames, elapsed)
        log.info("gaze available in %.0f%% of frames", 100 * gaze_frames / max(total_frames, 1))
        lost = ", ".join(f"{name}={100 * n / max(total_frames, 1):.0f}%" for name, n in problems.items() if name)
        log.info("gaze lost because: %s", lost or "never lost")
        return confirmations
    finally:
        worker.stop()


def manual_tick(arrow: Target, driver, ctrl: ControllerState, now: float) -> tuple[ControllerState, str]:
    """The rider is looking at a manual arrow: drive that way this pass (forward, backward or spin in place).
    Called every pass while the gaze stays on it; the first pass off the arrow goes back to drive_tick, which
    sends STOP when there is no destination."""
    left, right = ARROW_WHEELS[arrow]
    driver.send(MotorCommand(left, right, False, now))
    if ctrl.state != State.MOVING:
        log.info("MANUAL %s: wheels %d,%d", ARROW_NAMES[arrow], left, right)
    return ControllerState(state=State.MOVING, held_target=arrow), f"  |  MANUAL {ARROW_NAMES[arrow]} wheels {left},{right}"


def drive_tick(sel: Selection, hit, targets: list[Track], frame_w: int, hfov: float, driver, ctrl: ControllerState,
               nav: NavState, now: float, log_lines: list[str], *, obstacles: Sequence[Track], frame_h: int,
               frame_t: float, stop_requests: tuple[StopRequest, ...] = (), rearm: bool = False,
               follow: str = "direct", route_m: np.ndarray | None = None, replan: bool = True,
               route_pending: bool = False):
    """One drive step: confirmed destination -> follow its route -> wheels, every pass.
    No dwell, no safety state machine, no stale-frame or arrival checks (Prakhar, Sun Nov 15: "if someone confirms
    something that means they confirmed it"). Only the stop key here, or X / triple blink in the loop, stops the
    chair; they also clear the destination. The ESP32's own 200 ms watchdog still stops it if commands stop coming.
    """
    if stop_requests:
        log.info("STOP key: chair stopped, destination cleared")
        sel = clear_destination(sel)
    target = next((t for t in targets if t.id == sel.confirmed), None)
    wheels = (0, 0)
    if target is not None:
        if follow == "route":
            (speed, turn), _ = follow_step(route_m)  # no route yet -> (0, 0) until the worker's first plan arrives
            wheels = to_wheels(speed, turn)
        elif replan:
            nav, wheels, _ = nav_step(nav, target, obstacles, frame_w, hfov, driver.distance_cm())
        else:
            wheels = to_wheels(nav.v, nav.w)  # between detections: keep the last speeds
    moving = wheels != (0, 0)
    driver.send(MotorCommand(int(wheels[0]), int(wheels[1]), not moving, now))
    state = State.MOVING if moving else State.STOPPED
    if state != ctrl.state:
        log.info("state %s -> %s", ctrl.state.value, state.value)
    ctrl = ControllerState(state=state)
    note = f"  |  {state.value}" + (f" wheels {int(wheels[0])},{int(wheels[1])}" if moving else "")
    if target is not None and follow == "route" and route_m is None:
        note += " (planning route)"
    return sel, ctrl, nav, note


def show_text(cv2, text: str) -> None:
    """Full-screen instruction (used during the jaw calibration)."""
    window.show(cv2, WINDOW, screens.jaw_instruction(CANVAS_W, CANVAS_H, text))  # same text, themed card
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


def session_log_path() -> str:
    """Every run writes its log here (gitignored), so a session can be checked afterwards."""
    return os.path.join(SESSION_LOG_DIR, time.strftime("%Y-%m-%d_%H-%M-%S") + ".log")


def main(argv: list[str] | None = None) -> int:
    log_path = session_log_path()
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s",
                        handlers=[logging.StreamHandler(), logging.FileHandler(log_path)])
    # A second file with only the headset's lines: calibration, a level heartbeat every second, every clench.
    jaw_log = logging.FileHandler(log_path.replace(".log", "_jaw.log"))
    jaw_log.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
    logging.getLogger("bci.jaw_live").addHandler(jaw_log)
    log.info("session log: %s (headset only: %s)", log_path, jaw_log.baseFilename)
    parser = argparse.ArgumentParser(description="Choose a real object by looking at it.")
    parser.add_argument("--source", default="auto", help="forward camera index/URL, or auto (= not the face camera)")
    parser.add_argument("--eye-camera", default="auto", help="camera that sees the rider's face, or auto")
    parser.add_argument("--calibration", default="data/raw/gaze_calibration.json")
    parser.add_argument("--hfov", type=float, default=load_hfov(), help="calibrated if data/raw/camera_calibration.json exists")
    parser.add_argument("--device", default="mps")
    parser.add_argument("--seconds", type=float, default=None)
    parser.add_argument("--confirm", choices=["dwell", "key", "jaw", "blink"], default="dwell",
                        help="dwell = look 1.5 s; key = look + J; jaw = look + jaw clench (OpenBCI)")
    parser.add_argument("--jaw-board", choices=["synthetic", "wifi", "dongle"], default="dongle",
                        help="--confirm jaw: synthetic = practice (J injects a fake clench)")
    parser.add_argument("--jaw-port", default=None, help="OpenBCI dongle port, e.g. /dev/cu.usbserial-DM0xxxxx")
    parser.add_argument("--jaw-channels", default="1", help="Cyton channels with an electrode, e.g. 1 or 1,2")
    parser.add_argument("--drive", action="store_true", help="drive to the confirmed object (needs --mock or --serial)")
    parser.add_argument("--follow", choices=("direct", "route"), default="direct",
                        help="direct = steer straight at the object; route = follow the shortest safe route on the floor")
    parser.add_argument("--cam-height", type=float, default=CAM_HEIGHT_M, help="forward camera height above floor (m)")
    parser.add_argument("--cam-pitch", type=float, default=CAM_PITCH_DEG, help="forward camera tilt down (degrees)")
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
        log.info("cameras: %s", ", ".join(f"{p.index} (widest face {p.face_width:.0%} of the picture)" for p in probes))
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
    try:
        model = YOLO(SEG_MODEL)  # traces each object's outline; Ultralytics downloads it on first use
    except Exception as error:  # offline and not downloaded yet: plain detector, brackets instead of outlines
        log.warning("segmentation model unavailable (%s): corner brackets instead of outlines", str(error)[:80])
        model = YOLO(DEFAULT_MODEL)
    window.open_fullscreen(cv2, WINDOW)  # frames are scaled to the real screen size (interface/window.py)
    jaw, driver = None, None
    if args.drive:
        from motors.driver import MotorDriver, open_serial
        from motors.mock_serial import MockSerial

        if args.mock:
            mock = MockSerial()
            driver = MotorDriver(lambda: mock)
        else:  # the real hoverboard goes through Keshav's chair_control library (firmware/chair_control/chair.py)
            from motors.chair_driver import ChairDriver

            driver = ChairDriver(args.serial)
        driver.start()  # streams STOP lines from now on
    try:
        if args.confirm == "jaw":
            jaw = start_jaw(cv2, args)
            if jaw is None:
                return 2
        confirmations = run(cv2, reader, model, relevant_class_ids(model.names), gaze_queue, args.hfov, args.device,
                            args.seconds, tracker_alive=lambda: process.poll() is None, confirm_mode=args.confirm,
                            jaw=jaw, driver=driver, follow=args.follow, cam_h=args.cam_height,
                            cam_pitch=args.cam_pitch)
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
