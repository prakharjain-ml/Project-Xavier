"""Route preview: outlined objects, a gaze cursor and a route that stays on the real floor. No motors.

    python -m vision.nav_preview                      # forward camera found automatically (the one without a face)
    python -m vision.nav_preview --image room.png     # run on a photo instead of a camera
    python -m vision.nav_preview --scene-ai off       # no Gemini: local floor estimate, route drawn dashed
    python -m vision.nav_preview --cam-height 0.9 --cam-pitch 20   # where the phone sits on the chair

The mouse stands in for the rider's eyes: rest it on an object for 1.5 s to choose it (same dwell rule as the
real gaze screen). Click STOP or press S to clear the destination. Q / ESC quits. Nothing is sent to any motor.

How the route is made (rules in docs/ROUTE_REQUIREMENTS.md): objects come from the segmentation model, floor
and extra no-go zones come from Gemini in the background, and the route is planned locally on what is left.
The existing drive planner's command is only logged; the on-screen route is not yet the route the chair drives.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from collections.abc import Sequence

import cv2
import numpy as np

from control.goto import NavState, nav_step
from control.navigation import NavConfig
from shared.protocol import DWELL_S
from vision import hud
from vision.detect_track import DEFAULT_MODEL, SEG_MODEL, Track, detect, focal_length_px, load_hfov, relevant_class_ids
from vision.floor_route import Route
from vision.object_select import Selection, dwell_fraction, hit_boxes, update_selection
from vision.route_scene import cursor_hit, floor_view, plan
from vision.scene_ai import SceneAdvisor, advice_valid, make_client

log = logging.getLogger("vision.nav_preview")

DEAD_ZONE = 10  # firmware speed units below this count as "stopped" (the board ignores |speed| < 50 anyway)
VIEW_W = 1280  # the camera frame is resized to this width before detection and drawing
# Phone lens height above the floor and downward tilt. Measured Sat Nov 14 on the table set-up: 35 in, level.
# Re-measure once the phone is mounted on the chair, or pass --cam-height / --cam-pitch.
CAM_HEIGHT_M, CAM_PITCH_DEG = 0.89, 0.0
FLOW_GAPS_S = 1.5  # chevrons move this many gaps per second toward the target (hud phase: 1.0 = one gap)
# The planner keeps the whole chair width clear; the ribbon on screen is a thinner path marker (a full-width
# ribbon covers most of the visible floor). Drawing only: clearance is still checked at full width.
RIBBON_DISPLAY_SCALE = 0.3
WINDOW = "Xavier route preview"
QUIT_KEYS, STOP_KEYS = (27, ord("q")), (ord("s"), ord(" "))


def direction_label(left: int, right: int) -> str:
    """Wheel speeds -> plain words (positive = forward)."""
    if abs(left) < DEAD_ZONE and abs(right) < DEAD_ZONE:
        return "STOP"
    if left * right < 0:  # wheels turning opposite ways: spinning in place
        return "SPIN RIGHT" if left > right else "SPIN LEFT"
    if abs(left - right) <= max(4, 0.1 * max(abs(left), abs(right))):
        return "FORWARD" if left + right > 0 else "BACKWARD"
    return "FORWARD + RIGHT" if left > right else "FORWARD + LEFT"


def status_line(target: Track | None, route: Route | None, verified: bool, ai_status: str) -> str:
    if target is None:
        return "Stopped · Rest the cursor on an object to choose it"
    if route is None:
        return f"Stopped · No safe route to the {target.label}"
    if verified:
        return f"Stopped · Route to the {target.label} on Gemini-checked floor · Awaiting confirmation"
    waiting = "checking the floor with Gemini" if ai_status == "analysing" else "local floor estimate"
    return f"Stopped · Route to the {target.label} is unverified ({waiting})"


def hud_state(tracks: Sequence[Track], sel: Selection, cursor, route: Route | None, verified: bool, status: str,
              now: float) -> hud.HudState:
    objects = []
    for t in tracks:
        confirmed, candidate = t.id == sel.confirmed, t.id == sel.candidate
        progress = 1.0 if confirmed else dwell_fraction(sel, now) if candidate else 0.0
        objects.append(hud.SceneObject(t.label.capitalize(), t.bbox, t.outline, confirmed or candidate, progress))
    return hud.HudState(objects=tuple(objects), cursor=cursor,
                        route_points=None if route is None else route.points,
                        route_half_width=None if route is None else route.half_width_px * RIBBON_DISPLAY_SCALE,
                        route_verified=verified, status=status, phase=now * FLOW_GAPS_S)


class Mouse:
    """Latest mouse position (in camera-frame pixels) and whether STOP was clicked. Written by OpenCV's callback."""

    def __init__(self) -> None:
        self.cursor: tuple[float, float] | None = None
        self.stop_clicked = False
        self.frame_size = (VIEW_W, 720)

    def on_event(self, event: int, x: int, y: int, _flags: int, _param) -> None:
        ox, oy = hud.frame_origin()
        w, h = self.frame_size
        inside = 0 <= x - ox < w and 0 <= y - oy < h
        self.cursor = (float(x - ox), float(y - oy)) if inside else None
        if event == cv2.EVENT_LBUTTONDOWN:
            x1, y1, x2, y2 = hud.stop_button_rect(w, h)
            self.stop_clicked = self.stop_clicked or (x1 <= x < x2 and y1 <= y < y2)

    def take_stop(self) -> bool:
        clicked, self.stop_clicked = self.stop_clicked, False
        return clicked


class StillImage:
    """A photo that behaves like a camera: the same frame with a fresh timestamp on every read."""

    def __init__(self, path: str) -> None:
        self.frame = cv2.imread(path)
        if self.frame is None:
            raise FileNotFoundError(f"cannot read image {path}")

    def latest(self):
        return self.frame, time.monotonic()

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass


def run(reader, model, classes, hfov: float, seconds: float | None, cam_h: float, pitch: float,
        advisor: SceneAdvisor | None = None, fixed_cursor: tuple[float, float] | None = None,
        show: bool = True) -> np.ndarray | None:
    """Main loop. Returns the last rendered screen (None if no frame ever arrived)."""
    cfg, nav, sel, mouse = NavConfig(), NavState(), Selection(), Mouse()
    last_t, last_log, screen, start = None, 0.0, None, time.monotonic()
    if show:
        cv2.namedWindow(WINDOW)
        cv2.setMouseCallback(WINDOW, mouse.on_event)
    while seconds is None or time.monotonic() - start < seconds:
        key = cv2.waitKey(1) & 0xFF if show else 255
        if key in QUIT_KEYS:
            break
        snapshot = reader.latest()
        if snapshot is None or snapshot[1] == last_t:
            continue
        raw, last_t = snapshot
        frame = cv2.resize(raw, (VIEW_W, int(raw.shape[0] * VIEW_W / raw.shape[1])))  # same view, fewer pixels
        h, w = frame.shape[:2]
        mouse.frame_size, now = (w, h), time.monotonic()
        tracks = detect(model, frame, focal_length_px(w, hfov), "mps", classes)
        cursor = (fixed_cursor[0] * w, fixed_cursor[1] * h) if fixed_cursor is not None else mouse.cursor
        hit = cursor_hit(tracks, cursor)
        sel = update_selection(sel, hit, now, box=hit_boxes(tracks, w, h).get(hit))  # same dwell rule as real gaze
        if key in STOP_KEYS or mouse.take_stop():
            sel = Selection()  # STOP clears the destination (C9); this preview has no motors to stop
        target = next((t for t in tracks if t.id == sel.confirmed), None)
        advice = advisor.latest() if advisor is not None else None
        if advice is not None and not advice_valid(advice, frame, now):
            advice = None  # the view changed or the answer is old: do not trust it (C6)
        route, verified, wheels, arrived = None, False, (0, 0), False
        if target is not None:
            if advisor is not None and (advice is None or advice.target_id != target.id):
                advisor.submit(frame, now, target.id, target.label, target.bbox)  # never blocks; rate-limited inside
            route, verified = plan((h, w), tracks, target, advice, floor_view(w, h, hfov, cam_h, pitch))
            nav, wheels, arrived = nav_step(nav, target, tracks, w, hfov, distance_cm=None, cfg=cfg)
        else:
            nav = NavState()
        ai_status = advisor.status() if advisor is not None else "off"
        status = status_line(target, route, verified, ai_status)
        screen = hud.render(frame, hud_state(tracks, sel, cursor, route, verified, status, now))
        if show:
            cv2.imshow(WINDOW, screen)
        if now - last_log >= 1.0:
            last_log = now
            command = "NO TARGET" if target is None else "ARRIVED" if arrived else direction_label(*wheels)
            log.info("objects=%d target=%s route=%s floor=%s gemini=%s | drive planner: %s (left %+d, right %+d)",
                     len(tracks), "none" if target is None else target.label,
                     "none" if route is None else f"{len(route.points)} pts",
                     "gemini" if verified else "local", ai_status, command, *wheels)
    return screen


def open_source(args) -> tuple[object, str]:
    """The frame source and a name for the log: a photo, a given camera, or the camera that does not see a face."""
    from vision.camera_source import LatestFrameReader, open_capture, parse_source

    if args.image:
        return StillImage(args.image), f"image {os.path.basename(args.image)}"
    source = args.source
    if source == "auto":
        from vision.camera_roles import probe_cameras

        rooms = [p.index for p in probe_cameras() if not p.sees_face]
        if not rooms:
            raise RuntimeError("no forward camera found (every camera sees a face, or none is connected)")
        source = str(rooms[0])
    return LatestFrameReader(parse_source(source), opener=open_capture), f"camera {source}"


def parse_cursor(text: str | None) -> tuple[float, float] | None:
    """'0.8,0.6' -> (0.8, 0.6): a fixed cursor as fractions of the frame, for rendering without a mouse."""
    if not text:
        return None
    x, y = (float(part) for part in text.split(","))
    if not (0.0 <= x <= 1.0 and 0.0 <= y <= 1.0):
        raise ValueError("--cursor needs two fractions between 0 and 1, like 0.8,0.6")
    return x, y


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    parser = argparse.ArgumentParser(description="Route preview: outlined objects, gaze cursor, route on the floor.")
    parser.add_argument("--source", default="auto", help="camera index, or auto = the camera without a face")
    parser.add_argument("--image", help="run on this photo instead of a camera")
    parser.add_argument("--seconds", type=float, default=None)
    parser.add_argument("--cam-height", type=float, default=CAM_HEIGHT_M, help="camera height above floor (m)")
    parser.add_argument("--cam-pitch", type=float, default=CAM_PITCH_DEG, help="camera tilt down (degrees)")
    parser.add_argument("--scene-ai", choices=("gemini", "off"), default="gemini",
                        help="gemini = send downscaled frames to Gemini to find the floor; off = local estimate only")
    parser.add_argument("--cursor", help="fixed cursor as fractions x,y (instead of the mouse)")
    parser.add_argument("--save", help="write the last rendered screen to this PNG on exit")
    parser.add_argument("--no-window", action="store_true", help="render without opening a window (use with --save)")
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    from ultralytics import YOLO

    try:
        reader, name = open_source(args)
        fixed_cursor = parse_cursor(args.cursor)
    except (RuntimeError, FileNotFoundError, ValueError) as error:
        log.error("%s", error)
        return 2
    has_outlines = os.path.exists(SEG_MODEL)
    if not has_outlines:
        log.warning("segmentation model %s not found: objects get corner brackets instead of outlines", SEG_MODEL)
    model = YOLO(SEG_MODEL if has_outlines else DEFAULT_MODEL)
    client = make_client() if args.scene_ai == "gemini" else None
    advisor = SceneAdvisor(client) if client is not None else None
    if args.scene_ai == "gemini" and advisor is None:
        log.warning("no GEMINI_API_KEY: the floor is a local estimate and the route is drawn as unverified")
    log.info("%s, field of view %.1f deg, scene AI %s", name, load_hfov(), "gemini" if advisor else "off")
    reader.start()
    if advisor is not None:
        advisor.start()
    try:
        screen = run(reader, model, relevant_class_ids(model.names), load_hfov(), args.seconds, args.cam_height,
                     args.cam_pitch, advisor, fixed_cursor, show=not args.no_window)
    finally:
        reader.stop()
        if advisor is not None:
            advisor.stop()
        cv2.destroyAllWindows()
    if args.save and screen is not None:
        cv2.imwrite(args.save, screen)
        log.info("saved %s", args.save)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
