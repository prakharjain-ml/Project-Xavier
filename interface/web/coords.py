"""Coordinate contract between the gaze tracker, the browser layout and the camera frame.

1. Gaze trackers report a point as a FRACTION OF THE SCREEN (0..1), because they were calibrated on full-screen
   targets (EyeTrax predicts screen pixels; we divide by the screen size).
2. Calibration and driving run in browser fullscreen, so the page viewport IS the screen: a screen fraction is a
   viewport fraction. (Practice mode's mouse pointer is reported as a viewport fraction directly.)
3. The camera picture is drawn with object-fit: contain inside the video element, so it may have letterbox bars.
   Gaze on a bar is on no object: it maps to None, never clamped onto the picture's edge.
4. Object boxes stay in source-frame pixels; hit tests use frame fractions (vision.object_select.hit_boxes).
5. A calibration is only valid for the screen geometry it was made on (screen size, devicePixelRatio,
   fullscreen). Anything else invalidates it (see geometry_changed).
"""

from __future__ import annotations

from dataclasses import dataclass

Point = tuple[float, float]
Rect = tuple[float, float, float, float]  # x, y, width, height in CSS pixels


@dataclass(frozen=True)
class Layout:
    """What the browser reports on every layout change (all in CSS pixels)."""
    viewport_w: float
    viewport_h: float
    screen_w: float
    screen_h: float
    dpr: float
    fullscreen: bool
    video: Rect | None = None  # the video element's box in the viewport, None when no video is shown


def contain_rect(box: Rect, frame_w: int, frame_h: int) -> Rect:
    """Where a frame_w x frame_h picture actually appears inside `box` with object-fit: contain."""
    x, y, w, h = box
    if frame_w <= 0 or frame_h <= 0 or w <= 0 or h <= 0:
        return (x, y, 0.0, 0.0)
    scale = min(w / frame_w, h / frame_h)
    cw, ch = frame_w * scale, frame_h * scale
    return (x + (w - cw) / 2, y + (h - ch) / 2, cw, ch)


def viewport_to_frame(point: Point | None, layout: Layout, frame_w: int, frame_h: int) -> Point | None:
    """Viewport fraction -> fraction of the camera frame (0..1), or None when the point is not on the picture."""
    if point is None or layout.video is None:
        return None
    cx, cy, cw, ch = contain_rect(layout.video, frame_w, frame_h)
    if cw <= 0 or ch <= 0:
        return None
    px, py = point[0] * layout.viewport_w, point[1] * layout.viewport_h
    fx, fy = (px - cx) / cw, (py - cy) / ch
    if not (0.0 <= fx <= 1.0 and 0.0 <= fy <= 1.0):
        return None  # on a letterbox bar or outside the video: looking at no object
    return fx, fy


def frame_to_viewport(point: Point, layout: Layout, frame_w: int, frame_h: int) -> Point | None:
    """Frame fraction -> viewport fraction (for drawing / tests). None without a video box."""
    if layout.video is None:
        return None
    cx, cy, cw, ch = contain_rect(layout.video, frame_w, frame_h)
    return ((cx + point[0] * cw) / layout.viewport_w, (cy + point[1] * ch) / layout.viewport_h)


def screen_matches_viewport(layout: Layout, tolerance_px: float = 4.0) -> bool:
    """True in real fullscreen: the viewport covers the whole screen, so screen fractions are viewport fractions."""
    return (layout.fullscreen and abs(layout.viewport_w - layout.screen_w) <= tolerance_px
            and abs(layout.viewport_h - layout.screen_h) <= tolerance_px)


def geometry_changed(calibrated: Layout | None, now: Layout) -> bool:
    """A change that moves where a screen fraction lands: another screen size, zoom (devicePixelRatio) or leaving
    fullscreen. Resizing the video panel alone does NOT invalidate (it is handled by viewport_to_frame)."""
    if calibrated is None:
        return True
    return (abs(calibrated.screen_w - now.screen_w) > 1 or abs(calibrated.screen_h - now.screen_h) > 1
            or abs(calibrated.dpr - now.dpr) > 1e-3 or not screen_matches_viewport(now))
