"""Shared by the mouse preview (vision/nav_preview.py) and the real gaze screen (vision/object_select.py):
which object is under the cursor, and the route to the chosen object on free floor.

Rules are in docs/ROUTE_REQUIREMENTS.md. Pure functions: no camera, no window, no network."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

import cv2
import numpy as np

from vision.destinations import iou
from vision.detect_track import Track
from vision.floor import horizon_row, project_floor
from vision.floor_route import Route, free_floor, half_width_px, plan_route, polygons_to_mask
from vision.floor_seg import colour_floor
from vision.scene_ai import SceneAdvice

CHAIR_HALF_WIDTH_M = 0.3  # half the chair's width (VERIFY on the chair)
# The chair does not track the route perfectly (8.4 cm off at worst in simulation, see control/follow.py), so
# routes are planned for a chair this much wider on each side than it really is.
FOLLOW_MARGIN_M = 0.08
# Phone lens height above the floor and downward tilt. Measured Sat Nov 14 on the table set-up: 35 in, level.
# Re-measure once the phone is mounted on the chair, or pass --cam-height / --cam-pitch.
CAM_HEIGHT_M, CAM_PITCH_DEG = 0.89, 0.0
# The ribbon on screen is a thinner path marker than the chair (a full-width ribbon covers most of the visible
# floor). Drawing only: clearance is planned and checked at the full width above.
RIBBON_DISPLAY_SCALE = 0.3
CELL_M = 0.01  # top view resolution: 1 pixel = 1 cm of floor
MAX_RANGE_M = 6.0  # plan at most this far ahead (distance estimates and floor detail are poor beyond it)
HALF_SPAN_M = 3.0  # top view covers this far to the left and to the right
NEAR_MARGIN = 1.02  # start the top view 2% beyond the nearest visible floor, safely inside the image
SAME_OBJECT_IOU = 0.4  # a Gemini box overlapping a detected object's box this much is that same object
# The strip of floor between the chair and the nearest floor the camera sees is never seen. An object whose
# outline runs off the bottom of the picture has its foot somewhere in that strip. We assume that foot is at
# least this far ahead of the camera (anything nearer is the forward ultrasonic stop's job; VERIFY on the chair).
BLIND_MIN_M = 0.6
CUT_OFF_BAND = 0.02  # an outline reaching the bottom 2% of the picture counts as running off it
ROUNDING_SLACK_PX = 3  # pixels of rounding error allowed when a top-view point is mapped back to the image


def track_mask(track: Track, shape: tuple[int, int]) -> np.ndarray:
    """Pixels the object covers: its traced outline, or its whole box when the model gave no outline."""
    mask = np.zeros(shape, np.uint8)
    if track.outline is not None:
        cv2.fillPoly(mask, [np.round(track.outline).astype(np.int32)], 1)
    else:
        x1, y1, x2, y2 = (int(round(v)) for v in track.bbox)
        cv2.rectangle(mask, (x1, y1), (x2, y2), 1, -1)
    return mask.astype(bool)


def contains(polygon: np.ndarray, point: tuple[float, float]) -> bool:
    return cv2.pointPolygonTest(np.asarray(polygon, np.float32), (float(point[0]), float(point[1])), False) >= 0


def cursor_hit(tracks: Sequence[Track], cursor: tuple[float, float] | None) -> int | None:
    """ID of the object under the cursor. The smallest one wins, so a vase on a table beats the table."""
    if cursor is None:
        return None
    hits = []
    for t in tracks:
        x1, y1, x2, y2 = t.bbox
        inside = contains(t.outline, cursor) if t.outline is not None else (x1 <= cursor[0] <= x2 and y1 <= cursor[1] <= y2)
        if inside:
            hits.append(((x2 - x1) * (y2 - y1), t.id))
    return min(hits)[1] if hits else None


@dataclass(frozen=True, eq=False)
class FloorView:
    """The floor seen from above, in metres, and how it maps to the camera image.

    Why: clearance cannot be measured in image pixels. Near the horizon one pixel of image height is a lot of
    floor, while one pixel of width is little, so "keep 30 cm clear" means a different number of pixels in each
    direction and at each row. Seen from above every centimetre is the same size, so the chair's width is one
    constant. Routes are planned in this top view and then drawn back onto the camera image.

    Top view layout: 1 pixel = cell_m metres; the top row is far_m ahead of the camera, the bottom row is
    near_m ahead (the nearest floor the camera can see); the centre column is straight ahead, left is left."""

    to_image: np.ndarray  # 3x3 matrix: top-view pixel -> camera-image pixel
    shape: tuple[int, int]  # top view (rows, columns)
    cell_m: float
    near_m: float
    far_m: float
    horizon: float  # image row of the horizon
    width_gain: float  # chair half-width in image pixels per row below the horizon (for drawing the ribbon)


def floor_view(frame_w: int, frame_h: int, hfov_deg: float, cam_height_m: float, pitch_deg: float,
               chair_half_width_m: float = CHAIR_HALF_WIDTH_M) -> FloorView:
    focal = (frame_w / 2) / math.tan(math.radians(hfov_deg) / 2)
    # Steepest ray the camera sees = its tilt + half its vertical field of view. Where that ray meets the floor
    # is the nearest visible floor. Start the top view just beyond it.
    steepest = math.radians(pitch_deg) + math.atan((frame_h / 2) / focal)
    near = NEAR_MARGIN * cam_height_m / math.tan(steepest)
    rows, cols = int((MAX_RANGE_M - near) / CELL_M), int(2 * HALF_SPAN_M / CELL_M)
    corners_m = np.array([[MAX_RANGE_M, HALF_SPAN_M], [MAX_RANGE_M, -HALF_SPAN_M],
                          [near, -HALF_SPAN_M], [near, HALF_SPAN_M]])  # (forward, left) of the top view's corners
    corners_top = np.array([[0, 0], [cols, 0], [cols, rows], [0, rows]], np.float32)
    corners_image = project_floor(corners_m, frame_w, frame_h, hfov_deg, cam_height_m, pitch_deg)
    # Floor -> image is a perspective map of a flat plane, so four matching corners define it exactly.
    to_image = cv2.getPerspectiveTransform(corners_top, corners_image.astype(np.float32))
    return FloorView(to_image, (rows, cols), CELL_M, near, MAX_RANGE_M,
                     horizon_row(frame_w, frame_h, hfov_deg, pitch_deg), chair_half_width_m / cam_height_m)


def top_view(mask: np.ndarray, view: FloorView) -> np.ndarray:
    """Camera-image mask -> top-view mask. Floor the camera cannot see comes out False (unknown = not drivable)."""
    rows, cols = view.shape
    warped = cv2.warpPerspective(mask.astype(np.uint8), view.to_image, (cols, rows),
                                 flags=cv2.INTER_NEAREST | cv2.WARP_INVERSE_MAP, borderValue=0)
    return warped.astype(bool)


def image_points(points_top: np.ndarray, view: FloorView) -> np.ndarray:
    """Top-view pixels -> camera-image pixels."""
    return cv2.perspectiveTransform(np.asarray(points_top, np.float32).reshape(-1, 1, 2), view.to_image).reshape(-1, 2)


def top_points(points_image: np.ndarray, view: FloorView) -> np.ndarray:
    """Camera-image pixels -> top-view pixels. Points at or above the horizon are not floor and are dropped."""
    points = np.asarray(points_image, np.float32).reshape(-1, 2)
    points = points[points[:, 1] > view.horizon + 1]
    if len(points) == 0:
        return points
    return cv2.perspectiveTransform(points.reshape(-1, 1, 2), np.linalg.inv(view.to_image)).reshape(-1, 2)


def extra_no_go(no_go: Sequence[tuple[str, np.ndarray]], tracks: Sequence[Track], target: Track) -> list[np.ndarray]:
    """Gemini's no-go shapes for things the detector did NOT find (tables, walls, glass).

    Gemini boxes the whole object, top to bottom, which covers far more floor than the object stands on. For
    an object the detector also found we already have its exact outline, so Gemini's rough box only removes
    good floor: drop it. The same goes for its box around the target, which would block the floor in front."""
    centre = ((target.bbox[0] + target.bbox[2]) / 2, (target.bbox[1] + target.bbox[3]) / 2)
    kept = []
    for _label, polygon in no_go:
        xs, ys = polygon[:, 0], polygon[:, 1]
        box = (float(xs.min()), float(ys.min()), float(xs.max()), float(ys.max()))
        same_as_detected = any(iou(box, t.bbox) >= SAME_OBJECT_IOU for t in tracks)
        if not same_as_detected and not contains(polygon, centre):
            kept.append(polygon)
    return kept


def floor_metres(points_image: np.ndarray, view: FloorView) -> np.ndarray:
    """Camera-image pixels on the floor -> metres in the chair's frame: (forward, left), camera at (0, 0).

    This is what the route follower (control/follow.py) drives on. Points at or above the horizon are dropped."""
    top = top_points(points_image, view)
    rows, cols = view.shape
    forward = view.far_m - top[:, 1] * (view.far_m - view.near_m) / rows  # top row = far_m, bottom row = near_m
    left = HALF_SPAN_M - top[:, 0] * (2 * HALF_SPAN_M) / cols  # left column = +HALF_SPAN_M, right = -HALF_SPAN_M
    return np.stack([forward, left], axis=1)


def cut_off_spans(tracks: Sequence[Track], shape: tuple[int, int], view: FloorView) -> list[tuple[float, float]]:
    """For every object whose outline runs off the bottom of the picture: how far left and right it reaches,
    in metres (left positive), measured at the nearest floor the camera can see."""
    height, _width = shape
    band = max(1, int(CUT_OFF_BAND * height))
    spans = []
    for t in tracks:
        columns = np.flatnonzero(track_mask(t, shape)[height - band:].any(axis=0))
        if len(columns):
            edges = np.array([[columns[0], height - 1], [columns[-1], height - 1]], float)
            sides = floor_metres(edges, view)[:, 1]
            spans.append((float(sides.min()), float(sides.max())))
    return spans


def blind_strip_clear(start_left_m: float, spans: Sequence[tuple[float, float]], near_m: float,
                      half_width_m: float) -> bool:
    """Can the chair cross the unseen strip, straight from where it stands to the route's first point?

    The chair and a cut-off object are both seen from the camera, so the gap between them shrinks in proportion
    as you come nearer: a gap g at the nearest visible floor (near_m away) is only g * d / near_m at distance
    d. The object's foot may be as near as BLIND_MIN_M, so the chair's half-width must still fit there:
    g * BLIND_MIN_M / near_m > half_width, i.e. g > half_width * near_m / BLIND_MIN_M. A camera tilted down
    sees floor nearer (smaller near_m), which makes this far easier to pass."""
    needed = half_width_m * near_m / BLIND_MIN_M
    return all(start_left_m - right > needed or left - start_left_m > needed for left, right in spans)


def image_free_floor(frame: np.ndarray, tracks: Sequence[Track], target: Track,
                     advice: SceneAdvice | None, horizon: float) -> np.ndarray:
    """Free floor in the camera image.

    The floor itself is found by colour (vision/floor_seg.py). Objects from the detector are always removed
    (C5). Valid Gemini advice removes more: its no-go zones for things the detector does not know. Gemini's
    own floor outline is not used: it proved too rough (a strip along the bottom edge on the hall test frame)."""
    shape = frame.shape[:2]
    objects = np.zeros(shape, bool)
    for t in tracks:
        objects = objects | track_mask(t, shape)
    no_go = np.zeros(shape, bool) if advice is None else polygons_to_mask(extra_no_go(advice.no_go, tracks, target), shape)
    return free_floor(colour_floor(frame, objects, horizon), objects, no_go)


def plan(frame: np.ndarray, tracks: Sequence[Track], target: Track, advice: SceneAdvice | None,
         view: FloorView) -> tuple[Route | None, bool]:
    """Route to the target on free floor (in camera-image pixels), and whether Gemini's no-go zones for this
    view were applied (C12).

    Planned in the top view with the chair's real width, then mapped back onto the image. Any route point that
    does not land on free floor in the image means no route at all (C1, C4)."""
    shape, verified = frame.shape[:2], advice is not None
    free = image_free_floor(frame, tracks, target, advice, view.horizon)
    via = None
    if advice is not None and advice.target_id == target.id and len(advice.route):
        # Gemini's suggested points are hints. Keep only those that are on free floor in the image (it often
        # ends its route on the object itself, and one bad point would make the planner discard them all).
        hints = np.asarray(advice.route, float).reshape(-1, 2)
        cols, rows = np.round(hints[:, 0]).astype(int), np.round(hints[:, 1]).astype(int)
        inside = (cols >= 0) & (cols < shape[1]) & (rows >= 0) & (rows < shape[0])
        on_floor = inside.copy()
        on_floor[inside] = free[rows[inside], cols[inside]]
        via = top_points(hints[on_floor], view)
    route = plan_route(top_view(free, view), top_view(track_mask(target, shape), view), 0.0, 0.0,
                       via if via is not None and len(via) else None,
                       fixed_half_width_px=(CHAIR_HALF_WIDTH_M + FOLLOW_MARGIN_M) / view.cell_m)
    if route is None:
        return None, verified
    points = image_points(route.points, view)
    # The warp rounds to whole pixels, so allow a few pixels of slack before calling a point "off the floor".
    slack = cv2.dilate(free.astype(np.uint8), np.ones((2 * ROUNDING_SLACK_PX + 1,) * 2, np.uint8)).astype(bool)
    cols = np.clip(np.round(points[:, 0]).astype(int), 0, shape[1] - 1)
    rows = np.clip(np.round(points[:, 1]).astype(int), 0, shape[0] - 1)
    if not slack[rows, cols].all():
        return None, verified
    start_left_m = float(floor_metres(points[:1], view)[0, 1])
    if not blind_strip_clear(start_left_m, cut_off_spans(tracks, shape, view), view.near_m,
                             CHAIR_HALF_WIDTH_M + FOLLOW_MARGIN_M):
        return None, verified  # an object stands in the unseen strip too near the way in: no route (C13)
    widths = half_width_px(points[:, 1], view.horizon, view.width_gain)
    return Route(points=points, half_width_px=widths, via_gemini=route.via_gemini), verified
