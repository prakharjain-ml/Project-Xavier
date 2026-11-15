"""On-screen look for the route preview (contract: docs/ROUTE_REQUIREMENTS.md, section "vision/hud.py").

`render(frame, state)` returns a NEW image: a dark top bar, the camera frame with cyan overlays, and a dark bottom
bar with the red STOP button (C9). Pure drawing with cv2 + Pillow: no window, no camera, inputs never modified.

How one frame is built (kept under 25 ms on a 1280 x 720 frame, the frame-rate half of C11):
1. The two bars are drawn once with Pillow and cached, so their text costs nothing per frame.
2. See-through fills (chosen object, route, stop ring) are painted into one grey "tint" layer and blended in
   a single step, only inside the rectangle that the fills actually cover.
3. Glows are wide strokes painted into a quarter-size layer, blurred there (16x fewer pixels than a full-frame
   blur), enlarged, and added on top as light.
4. Crisp lines (outlines, route edges, chevrons, reticle, cursor) go on last so they stay sharp.
"""

from __future__ import annotations

import functools
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

# ---- Fonts (macOS). A missing file falls back to Pillow's built-in font, so the screen never crashes over a font.
AVENIR_NEXT = "/System/Library/Fonts/Avenir Next.ttc"
DIN_BOLD = "/System/Library/Fonts/Supplemental/DIN Alternate Bold.ttf"
# face name -> (font file, index of the face inside that file). Avenir Next.ttc: 0 Bold, 2 Demi Bold, 5 Medium.
FONT_FILES: dict[str, tuple[str, int]] = {"bold": (AVENIR_NEXT, 0), "demi": (AVENIR_NEXT, 2),
                                          "medium": (AVENIR_NEXT, 5), "num": (DIN_BOLD, 0)}

# ---- Colours as (R, G, B); `_bgr` flips them for OpenCV. Sampled from the team's reference images.
BAR_RGB = (20, 23, 32)          # near-black navy bars
PILL_RGB = (24, 26, 33)         # label pill
WHITE_RGB = (255, 255, 255)
TITLE_GREY_RGB = (186, 190, 198)   # "CAMERA VIEW"
STATUS_GREY_RGB = (160, 164, 173)  # status line
DIVIDER_RGB = (72, 76, 87)
STOP_RGB = (227, 37, 37)
CYAN_RGB = (8, 232, 248)        # bright lines and glow
PALE_CYAN_RGB = (118, 226, 238)  # thin outline of objects that are not chosen
FILL_RGB = (0, 170, 180)        # see-through fill (darker teal than the lines, as in the reference)
DIM_CYAN_RGB = (10, 165, 178)   # unverified route (C12): dimmer than a checked one

# ---- Layout in pixels (the reference scaled to a 1280-wide frame).
TOP_BAR_H = 46
BOTTOM_BAR_H = 72
BAR_MARGIN = 28                 # gap between the screen edge and the first/last thing in a bar
TITLE_FONT_PX, TITLE_TRACKING_PX = 23, 1.6   # tracking = extra space between the title's letters
SUBTITLE_FONT_PX = 18
MODE_FONT_PX, STATUS_FONT_PX, STOP_FONT_PX, LABEL_FONT_PX = 24, 20, 23, 19
ICON_W = 48                     # route icon box, starting at BAR_MARGIN
MODE_X = BAR_MARGIN + ICON_W + 20
DIVIDER_GAP = 38                # space on each side of the thin divider
DIVIDER_INSET = 18              # divider stops this far from the bar's top and bottom
STOP_W, STOP_H = 166, 50
STOP_SQUARE = 20                # white square icon inside the button
STOP_SQUARE_X, STOP_TEXT_X = 36, 70   # offsets from the button's left edge
TEXT_CLEARANCE = 16             # bar text must end this far before the STOP button
SUPERSAMPLE = 3                 # Pillow shapes are drawn 3x too big, then shrunk, which smooths their edges

# ---- Overlay geometry.
SHIFT = 4                       # OpenCV fixed-point: coordinates in 1/16 px, so thin lines sit between pixels
COORD_LIMIT = 8000.0            # clamp far-off-screen points so the fixed-point ints stay small
TINY = 1e-9                     # added before dividing by a length that could be zero
GLOW_SCALE = 4                  # glow layer is 1/4 size in each direction
GLOW_SIGMA = 1.7                # blur on the small layer (about 7 px on screen)
GLOW_GAIN = 0.9                 # brightness of the added glow
GLOW_STROKE = 1                 # stroke width on the small layer (about 4 px on screen)
OUTLINE_PX, SELECTED_OUTLINE_PX = 1, 3
OUTLINE_STEP_PX = 4.0           # traced shapes are re-sampled to one point every 4 px ...
OUTLINE_SMOOTH = 5              # ... and averaged over 5 of them, which irons out stair-steps
OBJECT_FILL_ALPHA = 150         # 0..255 strength of the chosen object's fill
LOOKED_FILL_ALPHA = 45          # much lighter fill while the object is only being looked at (not yet confirmed)
BRACKET_FILL_ALPHA = 46         # lighter fill when we only have a box, not the object's real shape
BRACKET_ARM_FRAC, BRACKET_ARM_MIN, BRACKET_ARM_MAX = 0.18, 8, 28
RETICLE_FRAC, RETICLE_MIN, RETICLE_MAX = 0.15, 14, 34   # radius = fraction of the object's smaller side
RETICLE_ARC_PX, RETICLE_DOT_PX = 6, 4
PILL_H, PILL_PAD_X, PILL_RADIUS, PILL_OPACITY = 46, 26, 19, 242
PILL_RISE = 20                  # gap between the object's top and the pill's bottom
PILL_SHIFT_FRAC = 0.12          # pill sits a little right of the reticle (fraction of the object's width)
PILL_FOOT_FRAC = 0.62           # the leader line leaves the pill's bottom edge this far along its width
EDGE_MARGIN = 6                 # keep the pill this far inside the frame
ROUTE_STEP_PX = 6.0             # the route is re-sampled to one point every 6 px
TANGENT_SMOOTH = 9              # direction is averaged over 9 samples so the ribbon's edges do not zigzag
ROUTE_FILL_NEAR, ROUTE_FILL_FAR = 34, 92   # fill strength at the chair and at the target (0..255)
ROUTE_EDGE_PX = 2
CHEVRON_GAP_GAIN, CHEVRON_GAP_MIN_PX = 0.95, 9.0   # spacing = gain * half-width + min: closer together far away
CHEVRON_WING, CHEVRON_RISE, CHEVRON_THICK = 0.44, 0.55, 0.50  # wing: of half-width; rise, thick: of the wing
CHEVRON_MIN_HALF_PX = 5.0       # no chevrons where the ribbon is too thin to show them
CHEVRON_END_CLEAR = 0.45        # last chevron stays this many gaps before the stop ring
RING_WIDTH_GAIN, RING_MIN_PX, RING_MAX_PX = 2.3, 16.0, 90.0   # ring half-width from the route's end half-width
RING_OVER_RIBBON = 1.15         # ... but always at least this much wider than the ribbon that runs into it
RING_FLATTEN = 0.26             # ring height / width: a circle on the floor seen from the chair looks flat
RING_PX, RING_FILL_ALPHA = 2, 70
RING_POINTS = 48                # the ring is drawn as a polygon with this many corners
DASH_ON, DASH_OFF = 4, 4        # unverified route: 4 samples drawn, 4 skipped (16 px on, 16 px off)
CANVAS_PAD = 24                 # the ribbon is painted on a canvas this much bigger than the frame on every side
START_EDGE_PX = 4               # a route that starts this close to the bottom edge runs off-screen, no end line
MIN_EDGE_POINTS = 12            # ignore specks when tracing the ribbon's edge
RING_HIDE_PX = 3.0              # the ribbon's edge is not drawn inside the stop ring (plus this margin)
CURSOR_GLOW = 170               # 0..255 strength of the soft light under the cursor
# Floating chevrons (Google Maps Live View style, look after Polyfork's "Direction Chevron", CC BY 4.0):
# a flat rounded chevron, white face, cyan rim, a darker blue side for thickness, a soft shadow on the floor.
GUIDE_FACE_RGB = (246, 252, 255)
GUIDE_LIT_RGB = (176, 244, 252)   # the face tint that drifts from the nearest chevron to the farthest
GUIDE_SIDE_RGB = (18, 84, 146)    # the chevron's thickness, seen from slightly above
GUIDE_SHADOW_ALPHA = 0.32
GUIDE_ARM = (0.42, 0.3)            # chevron arm end, as a fraction of its width: (sideways, down from the tip)
GUIDE_STROKE = 0.24               # face stroke width, fraction of the chevron's width
GUIDE_RIM = 0.045                 # rim width each side, fraction of the width
GUIDE_DEPTH = (0.03, 0.075)       # offset of the side layer (thickness), fraction of the width
GUIDE_FLOW_PER_S = 0.7            # the highlight moves this many chevrons per second: slow, never a flash
GUIDE_LABEL_GAP = 10              # pixels between the farthest chevron and its label pill
CURSOR_R, CURSOR_PX, CURSOR_DOT_PX = 13, 2, 3


@dataclass(frozen=True)
class SceneObject:
    label: str
    bbox: tuple[float, float, float, float]   # x1, y1, x2, y2 in frame pixels
    outline: np.ndarray | None   # (N, 2) polygon; None = fall back to corner brackets on the bbox
    selected: bool = False
    progress: float = 0.0        # confirm progress 0..1, drawn as the reticle arc
    confirmed: bool = False      # the destination: strong fill and "· destination" on its label. Only looked at: light fill


@dataclass(frozen=True)
class HudState:
    objects: tuple[SceneObject, ...] = ()
    cursor: tuple[float, float] | None = None   # gaze point in frame pixels
    route_points: np.ndarray | None = None      # (N, 2) from the chair (bottom edge) to the stop point
    route_half_width: np.ndarray | None = None  # (N,) ribbon half-width in pixels at each point
    route_verified: bool = True                 # False = dashed, "unverified" (C12)
    title_left: str = "XAVIER"
    title_right: str = "CAMERA VIEW"
    mode: str = "Route preview"
    status: str = "Stopped · Awaiting confirmation"
    phase: float = 0.0                          # animates the chevrons: +1.0 moves each one a full gap forward
    guides: tuple = ()                          # floating 3D chevrons along the route (vision.chevrons.Guide)
    guide_label: str | None = None              # pill above the farthest chevron, e.g. "Toward chair · 2.4 m"
    clock: float = 0.0                          # seconds, drives the slow highlight that runs along the chevrons


@dataclass(frozen=True)
class _Ribbon:
    """The route re-sampled evenly, with everything the drawing steps need."""
    centre: np.ndarray   # (M, 2) points along the route, ROUTE_STEP_PX apart
    half: np.ndarray     # (M,) half-width at each point
    forward: np.ndarray  # (M, 2) unit direction of travel
    along: np.ndarray    # (M,) distance from the chair in pixels
    fill: np.ndarray     # (frame height, frame width) uint8: fill strength per pixel, 0 outside the ribbon
    edges: tuple[np.ndarray, ...]   # smoothed outlines of the ribbon in frame pixels, as open lines
    ring: np.ndarray     # (K, 2) the stop ring as a polygon
    ring_depth: float    # the ring's half-height: chevrons stop before it


# ---------------------------------------------------------------- public API

def frame_origin() -> tuple[int, int]:
    """(x, y) of the camera image's top-left corner inside the rendered image."""
    return 0, TOP_BAR_H


def stop_button_rect(frame_w: int, frame_h: int) -> tuple[int, int, int, int]:
    """STOP button as (x1, y1, x2, y2) in rendered-image pixels; a click with x1 <= x < x2 and y1 <= y < y2 hits."""
    x1, y1, x2, y2 = _stop_rect_in_bar(frame_w)
    bar_top = TOP_BAR_H + frame_h
    return x1, bar_top + y1, x2, bar_top + y2


def render(frame: np.ndarray, state: HudState) -> np.ndarray:
    """Camera frame with overlays, between the top and the bottom bar. `frame` is left untouched."""
    if frame.ndim != 3 or frame.shape[2] != 3 or frame.dtype != np.uint8:
        raise ValueError(f"frame must be a (height, width, 3) uint8 BGR image, got {frame.shape} {frame.dtype}")
    h, w = frame.shape[:2]
    out = np.empty((TOP_BAR_H + h + BOTTOM_BAR_H, w, 3), np.uint8)
    out[:TOP_BAR_H] = _top_bar(w, state.title_left, state.title_right)
    out[TOP_BAR_H + h:] = _bottom_bar(w, state.mode, state.status)
    view = out[TOP_BAR_H:TOP_BAR_H + h]  # a window into `out`: drawing on `view` draws on the result
    view[:] = frame
    ribbon = _build_ribbon(state, h, w)
    tint = np.zeros((h, w), np.uint8)  # how strongly each pixel gets the see-through fill
    glow = np.zeros((math.ceil(h / GLOW_SCALE), math.ceil(w / GLOW_SCALE)), np.uint8)  # quarter-size glow layer
    if ribbon is not None and state.route_verified:
        _route_underlay(tint, glow, ribbon, state.phase)
    for obj in state.objects:
        if obj.selected:
            _selected_underlay(tint, glow, obj)
    has_cursor = state.cursor is not None and bool(np.isfinite(state.cursor).all())
    if has_cursor:
        cv2.circle(glow, _point(state.cursor, for_glow=True), _px(CURSOR_R / GLOW_SCALE), CURSOR_GLOW, -1,
                   cv2.LINE_AA, SHIFT)
    _blend_tint(view, tint)
    _add_glow(view, glow)
    if ribbon is not None:
        _route_lines(view, ribbon, state.phase, state.route_verified)
    for obj in sorted(state.objects, key=lambda o: o.selected):  # chosen objects last, so they end up on top
        _object_lines(view, obj)
    if state.guides:
        _draw_guides(view, state.guides, state.clock, state.guide_label)
    if has_cursor:
        _cursor(view, state.cursor)  # last, so the gaze cursor is never hidden by anything else
    return out


def clear_caches() -> None:
    """Forget cached fonts, bars and label pills (used by tests that swap the font files)."""
    for cached in (_font, _top_bar, _bottom_bar, _bottom_bar_base, _label_pill):
        cached.cache_clear()


# ---------------------------------------------------------------- small helpers

def _bgr(rgb: tuple[int, int, int]) -> tuple[int, int, int]:
    return rgb[2], rgb[1], rgb[0]


def _fixed(points: np.ndarray, for_glow: bool = False) -> np.ndarray:
    """Float pixel points -> OpenCV fixed-point ints (1/16 px). `for_glow` gives the spot on the small glow layer:
    its pixel i covers frame pixels 4i..4i+3, whose middle is 4i + 1.5, hence the shift before the division."""
    points = np.asarray(points, np.float64)
    if for_glow:
        points = (points - (GLOW_SCALE - 1) / 2) / GLOW_SCALE
    return np.round(np.clip(points, -COORD_LIMIT, COORD_LIMIT) * (1 << SHIFT)).astype(np.int32)


def _point(xy: tuple[float, float], for_glow: bool = False) -> tuple[int, int]:
    x, y = _fixed(np.array(xy, np.float64), for_glow)
    return int(x), int(y)


def _px(length: float) -> int:
    """A length (radius, axis) in fixed-point units."""
    return int(round(length * (1 << SHIFT)))


def _polylines(img: np.ndarray, lines: list[np.ndarray], closed: bool, color, thickness: int,
               for_glow: bool = False) -> None:
    cv2.polylines(img, [_fixed(line, for_glow) for line in lines], closed, color, thickness, cv2.LINE_AA, SHIFT)


def _tinted(strength: np.ndarray, rgb: tuple[int, int, int], gain: float = 1.0) -> np.ndarray:
    """Grey layer -> colour image: `rgb` scaled by strength / 255 (and by `gain`), clipped at 255."""
    return cv2.merge([cv2.convertScaleAbs(strength, alpha=gain * channel / 255) for channel in _bgr(rgb)])


def _blend_tint(view: np.ndarray, tint: np.ndarray) -> None:
    """Mix the fill colour into `view` where `tint` is non-zero: pixel * (1 - a) + colour * a."""
    x, y, bw, bh = cv2.boundingRect(tint)  # work only inside the rectangle the fills cover (keeps this fast)
    if bw == 0:
        return
    roi, alpha = view[y:y + bh, x:x + bw], tint[y:y + bh, x:x + bw]
    kept = cv2.multiply(roi, cv2.merge([cv2.bitwise_not(alpha)] * 3), scale=1 / 255)  # bitwise_not = 255 - a
    roi[:] = cv2.add(kept, _tinted(alpha, FILL_RGB))


def _add_glow(view: np.ndarray, glow: np.ndarray) -> None:
    """Blur the small glow layer, enlarge it, and add it to `view` as cyan light."""
    if cv2.countNonZero(glow) == 0:
        return
    h, w = view.shape[:2]
    # Enlarge by exactly GLOW_SCALE (the small layer was rounded up in size), then cut back to the frame.
    full_size = (glow.shape[1] * GLOW_SCALE, glow.shape[0] * GLOW_SCALE)
    soft = cv2.resize(cv2.GaussianBlur(glow, (0, 0), GLOW_SIGMA), full_size, interpolation=cv2.INTER_LINEAR)[:h, :w]
    x, y, bw, bh = cv2.boundingRect(soft)
    roi = view[y:y + bh, x:x + bw]
    roi[:] = cv2.add(roi, _tinted(soft[y:y + bh, x:x + bw], CYAN_RGB, GLOW_GAIN))  # cv2.add stops at 255


# ---------------------------------------------------------------- route

def _build_ribbon(state: HudState, h: int, w: int) -> _Ribbon | None:
    """Turn the route polyline into a ribbon. None = nothing to draw (no route, too short, or NaN in it)."""
    if state.route_points is None:
        return None
    points = np.asarray(state.route_points, np.float64)
    if state.route_half_width is None or points.ndim != 2 or points.shape[1] != 2:
        raise ValueError("route_points must be (N, 2) and come with route_half_width")
    half_in = np.asarray(state.route_half_width, np.float64)
    if half_in.shape != (len(points),):
        raise ValueError(f"route_half_width must have shape ({len(points)},), got {half_in.shape}")
    if len(points) < 2 or not (np.isfinite(points).all() and np.isfinite(half_in).all()):
        return None  # a broken route is never drawn as if it were a route (C4)
    along_in = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(points, axis=0), axis=1))])
    if along_in[-1] < 2 * ROUTE_STEP_PX:
        return None
    along = np.linspace(0.0, along_in[-1], int(along_in[-1] / ROUTE_STEP_PX) + 1)
    centre = np.stack([np.interp(along, along_in, points[:, k]) for k in (0, 1)], axis=1)
    half = np.maximum(np.interp(along, along_in, half_in), 1.0)
    forward = _smoothed_directions(centre)
    ring_a = max(float(np.clip(RING_WIDTH_GAIN * half[-1], RING_MIN_PX, RING_MAX_PX)), RING_OVER_RIBBON * half[-1])
    ring_b = ring_a * RING_FLATTEN
    # A wide ribbon narrows over its last stretch so that its end fits inside the flat stop ring.
    drawn_half = np.minimum(half, ring_b + (along[-1] - along))
    sideways = np.stack([-forward[:, 1], forward[:, 0]], axis=1) * drawn_half[:, None]  # forward turned 90 degrees
    angles = np.linspace(0.0, 2 * math.pi, RING_POINTS, endpoint=False)
    ring = centre[-1] + np.stack([ring_a * np.cos(angles), ring_b * np.sin(angles)], axis=1)
    canvas = _ribbon_canvas(centre + sideways, centre - sideways, ring, centre[0, 1] >= h - START_EDGE_PX, h, w)
    edges = _traced_edges(canvas, centre[-1], (ring_a + RING_HIDE_PX, ring_b + RING_HIDE_PX))
    return _Ribbon(centre, half, forward, along, canvas[CANVAS_PAD:CANVAS_PAD + h, CANVAS_PAD:CANVAS_PAD + w],
                   edges, ring, ring_b)


def _smoothed_directions(centre: np.ndarray) -> np.ndarray:
    """Unit direction of travel at each point, averaged over a few neighbours. A planner's path has small
    stair-steps; without the averaging the ribbon's edges would copy them as a zigzag."""
    step = np.gradient(centre, axis=0)
    pad = TANGENT_SMOOTH // 2
    padded = np.pad(step, ((pad, pad), (0, 0)), mode="edge")
    kernel = np.full(TANGENT_SMOOTH, 1.0 / TANGENT_SMOOTH)
    smooth = np.stack([np.convolve(padded[:, k], kernel, mode="valid") for k in (0, 1)], axis=1)
    return smooth / (np.linalg.norm(smooth, axis=1, keepdims=True) + TINY)


def _ribbon_canvas(left: np.ndarray, right: np.ndarray, ring: np.ndarray, starts_at_bottom: bool, h: int, w: int
                   ) -> np.ndarray:
    """Paint the ribbon as fill strengths (faint at the chair, stronger at the target) on a canvas a bit bigger
    than the frame. Painting first and tracing the edge afterwards (see `_traced_edges`) keeps the edge clean
    on tight bends, where simply shifting the route sideways would make the inner edge loop over itself."""
    canvas = np.zeros((h + 2 * CANVAS_PAD, w + 2 * CANVAS_PAD), np.uint8)
    a, b = _fixed(left + CANVAS_PAD), _fixed(right + CANVAS_PAD)
    # One 4-corner patch per step along the route, painted as two triangles: on a tight bend the patch twists
    # into a bow-tie, which OpenCV cannot fill as one shape, but its two triangles always can be.
    first = np.stack([a[:-1], a[1:], b[1:]], axis=1)
    second = np.stack([a[:-1], b[1:], b[:-1]], axis=1)
    strengths = np.linspace(ROUTE_FILL_NEAR, ROUTE_FILL_FAR, len(first)).astype(int)
    if starts_at_bottom:
        # Push the chair end below the canvas, so the ribbon runs off the screen instead of ending in a line.
        drop = np.array([0, _px(2 * CANVAS_PAD)], np.int32)
        cv2.fillConvexPoly(canvas, np.stack([a[0], b[0], b[0] + drop, a[0] + drop]), ROUTE_FILL_NEAR, cv2.LINE_8,
                           SHIFT)
    for one, two, strength in zip(first, second, strengths):
        cv2.fillConvexPoly(canvas, one, int(strength), cv2.LINE_8, SHIFT)
        cv2.fillConvexPoly(canvas, two, int(strength), cv2.LINE_8, SHIFT)
    cv2.fillPoly(canvas, [_fixed(ring + CANVAS_PAD)], 0, cv2.LINE_8, SHIFT)  # the ribbon stops at the stop ring
    return canvas


def _traced_edges(canvas: np.ndarray, ring_centre: np.ndarray, ring_axes: tuple[float, float]
                  ) -> tuple[np.ndarray, ...]:
    """Outlines of the painted ribbon in frame pixels, cut open where they run along the stop ring (the ring is
    drawn there instead). Where the ribbon leaves the frame, its outline follows the canvas border, which is
    CANVAS_PAD pixels off-screen, so no stray line shows along the frame's edge."""
    contours, _ = cv2.findContours(canvas, cv2.RETR_LIST, cv2.CHAIN_APPROX_NONE)
    lines: list[np.ndarray] = []
    for contour in contours:
        if len(contour) < MIN_EDGE_POINTS:
            continue
        loop = _smooth_closed(contour[:, 0, :].astype(np.float64) - CANVAS_PAD)
        in_ring = (((loop - ring_centre) / ring_axes) ** 2).sum(axis=1) < 1.0  # inside the (slightly grown) ellipse
        lines.extend(_visible_runs(loop, in_ring))
    return tuple(lines)


def _visible_runs(loop: np.ndarray, hidden: np.ndarray) -> list[np.ndarray]:
    """Split a closed loop into the stretches where `hidden` is False (the whole loop if nothing is hidden)."""
    if not hidden.any():
        return [np.concatenate([loop, loop[:1]])]
    start = int(np.argmax(hidden))  # start at a hidden point, so no visible stretch wraps around the array's end
    loop, hidden = np.roll(loop, -start, axis=0), np.roll(hidden, -start)
    pieces = np.split(loop, np.flatnonzero(hidden))  # every piece after the first begins with a hidden point
    return [piece[1:] for piece in pieces if len(piece) > 2]


def _smooth_closed(shape: np.ndarray) -> np.ndarray:
    """Walk a closed shape in even 4 px steps and average each point with its neighbours (wrapping around).
    This irons out pixel stair-steps; a shape too small to survive the averaging is returned as it is."""
    closed = np.concatenate([shape, shape[:1]])
    along = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(closed, axis=0), axis=1))])
    count = int(along[-1] / OUTLINE_STEP_PX)
    if count < 2 * OUTLINE_SMOOTH:
        return shape
    marks = np.linspace(0.0, along[-1], count, endpoint=False)
    even = np.stack([np.interp(marks, along, closed[:, k]) for k in (0, 1)], axis=1)
    pad = OUTLINE_SMOOTH // 2
    wrapped = np.concatenate([even[-pad:], even, even[:pad]])
    kernel = np.full(OUTLINE_SMOOTH, 1.0 / OUTLINE_SMOOTH)
    return np.stack([np.convolve(wrapped[:, k], kernel, mode="valid") for k in (0, 1)], axis=1)


def _chevrons(ribbon: _Ribbon, phase: float) -> list[np.ndarray]:
    """Arrow-head polygons along the route. They are bigger and further apart where the ribbon is wide (near
    the chair), and `phase` slides them toward the target."""
    gap = CHEVRON_GAP_GAIN * ribbon.half + CHEVRON_GAP_MIN_PX
    count_so_far = np.cumsum(np.diff(ribbon.along, prepend=0.0) / gap)  # "how many gaps from the chair"
    last = np.interp(ribbon.along[-1] - ribbon.ring_depth, ribbon.along, count_so_far)  # where the ring begins
    offset = phase % 1.0 if math.isfinite(phase) else 0.0  # phase and phase + 1 look the same
    marks = np.arange(offset, last - CHEVRON_END_CLEAR, 1.0)
    index = np.interp(marks, count_so_far, np.arange(len(count_so_far)))
    shapes = []
    for i in index:
        lo = int(i)
        hi, t = min(lo + 1, len(ribbon.half) - 1), i - lo
        half = ribbon.half[lo] * (1 - t) + ribbon.half[hi] * t
        if half < CHEVRON_MIN_HALF_PX:
            continue
        tip = ribbon.centre[lo] * (1 - t) + ribbon.centre[hi] * t
        ahead = ribbon.forward[lo]
        side = np.array([-ahead[1], ahead[0]])
        wing = CHEVRON_WING * half
        rise, thick = CHEVRON_RISE * wing, CHEVRON_THICK * wing
        back = (rise - thick) / 2 - rise  # shifts the shape so it is centred on `tip`
        # (sideways, forward) corners: outer V left-to-right, then the inner V back again.
        corners = [(-wing, back), (0, back + rise), (wing, back), (wing, back - thick), (0, back + rise - thick),
                   (-wing, back - thick)]
        shapes.append(np.array([tip + s * side + f * ahead for s, f in corners]))
    return shapes


def _route_underlay(tint: np.ndarray, glow: np.ndarray, ribbon: _Ribbon, phase: float) -> None:
    """Checked route only: the see-through fill and the glow sources (edges, ring, chevrons)."""
    np.maximum(tint, ribbon.fill, out=tint)
    cv2.fillPoly(tint, [_fixed(ribbon.ring)], RING_FILL_ALPHA, cv2.LINE_AA, SHIFT)
    _polylines(glow, list(ribbon.edges), False, 255, GLOW_STROKE, for_glow=True)
    _polylines(glow, [ribbon.ring], True, 255, GLOW_STROKE, for_glow=True)
    chevrons = _chevrons(ribbon, phase)
    if chevrons:
        cv2.fillPoly(glow, [_fixed(c, for_glow=True) for c in chevrons], 255, cv2.LINE_AA, SHIFT)


def _dashes(line: np.ndarray) -> list[np.ndarray]:
    """Cut an evenly sampled line into short pieces with gaps between them."""
    return [line[i:i + DASH_ON + 1] for i in range(0, len(line) - 1, DASH_ON + DASH_OFF)]


def _route_lines(view: np.ndarray, ribbon: _Ribbon, phase: float, verified: bool) -> None:
    """Crisp route strokes. Checked: solid bright edges, filled chevrons, solid ring. Unverified (C12): dashed
    dim edges, hollow chevrons, dashed ring, and (see render) no fill and no glow."""
    chevrons = _chevrons(ribbon, phase)
    if verified:
        color = _bgr(CYAN_RGB)
        _polylines(view, list(ribbon.edges), False, color, ROUTE_EDGE_PX)
        if chevrons:
            cv2.fillPoly(view, [_fixed(c) for c in chevrons], color, cv2.LINE_AA, SHIFT)
        _polylines(view, [ribbon.ring], True, color, RING_PX)
        return
    color = _bgr(DIM_CYAN_RGB)
    ring = _smooth_closed(ribbon.ring)  # also re-samples the ring evenly, so its dashes have one length
    pieces = [piece for line in (*ribbon.edges, np.concatenate([ring, ring[:1]])) for piece in _dashes(line)]
    _polylines(view, pieces, False, color, ROUTE_EDGE_PX)
    if chevrons:
        _polylines(view, chevrons, True, color, 1)


# ---------------------------------------------------------------- objects

def _display_outline(obj: SceneObject) -> np.ndarray | None:
    """The object's outline, smoothed for drawing; None = no usable outline (draw corner brackets instead).
    The segmentation model's polygons follow a coarse mask, so they arrive as stair-steps about 8 px tall."""
    if obj.outline is None:
        return None
    outline = np.asarray(obj.outline, np.float64)
    if outline.ndim != 2 or outline.shape[1] != 2 or len(outline) < 3 or not np.isfinite(outline).all():
        return None
    return _smooth_closed(outline)


def _brackets(bbox: tuple[float, float, float, float]) -> list[np.ndarray]:
    """Four L-shaped corners of a box, used when the detector gave no outline."""
    x1, y1, x2, y2 = bbox
    arm = float(np.clip(BRACKET_ARM_FRAC * min(x2 - x1, y2 - y1), BRACKET_ARM_MIN, BRACKET_ARM_MAX))
    corners = (((x1, y1), (1, 1)), ((x2, y1), (-1, 1)), ((x2, y2), (-1, -1)), ((x1, y2), (1, -1)))
    return [np.array([(cx + dx * arm, cy), (cx, cy), (cx, cy + dy * arm)]) for (cx, cy), (dx, dy) in corners]


def _selected_underlay(tint: np.ndarray, glow: np.ndarray, obj: SceneObject) -> None:
    """Fill and glow sources for the chosen object."""
    if not np.isfinite(obj.bbox).all():
        return
    outline = _display_outline(obj)
    if outline is not None:
        cv2.fillPoly(tint, [_fixed(outline)], OBJECT_FILL_ALPHA if obj.confirmed else LOOKED_FILL_ALPHA, cv2.LINE_AA,
                     SHIFT)
        _polylines(glow, [outline], True, 255, GLOW_STROKE, for_glow=True)
        return
    x1, y1, x2, y2 = obj.bbox
    box = np.array([(x1, y1), (x2, y1), (x2, y2), (x1, y2)])
    cv2.fillPoly(tint, [_fixed(box)], BRACKET_FILL_ALPHA, cv2.LINE_AA, SHIFT)
    _polylines(glow, _brackets(obj.bbox), False, 255, GLOW_STROKE, for_glow=True)


def _object_lines(view: np.ndarray, obj: SceneObject) -> None:
    """Outline (or corner brackets) of one object; the chosen one also gets its reticle and label."""
    if not np.isfinite(obj.bbox).all():
        return
    color = _bgr(CYAN_RGB if obj.selected else PALE_CYAN_RGB)
    outline = _display_outline(obj)
    if outline is not None:
        _polylines(view, [outline], True, color, SELECTED_OUTLINE_PX if obj.selected else OUTLINE_PX)
    else:
        _polylines(view, _brackets(obj.bbox), False, color, SELECTED_OUTLINE_PX if obj.selected else OUTLINE_PX + 1)
    if obj.selected:
        _reticle_and_label(view, obj)


def _reticle_and_label(view: np.ndarray, obj: SceneObject) -> None:
    """Thin circle + centre dot + progress arc on the object, and a label pill joined to it by a thin line."""
    x1, y1, x2, y2 = obj.bbox
    centre = ((x1 + x2) / 2, (y1 + y2) / 2)
    radius = float(np.clip(RETICLE_FRAC * min(x2 - x1, y2 - y1), RETICLE_MIN, RETICLE_MAX))
    color = _bgr(CYAN_RGB)
    if obj.label:
        _label(view, obj, centre, radius)
    cv2.circle(view, _point(centre), _px(radius), color, 1, cv2.LINE_AA, SHIFT)
    cv2.circle(view, _point(centre), _px(RETICLE_DOT_PX), color, -1, cv2.LINE_AA, SHIFT)
    progress = min(1.0, max(0.0, obj.progress)) if math.isfinite(obj.progress) else 0.0
    if progress > 0:
        # Angles run clockwise on screen (y points down); -90 is 12 o'clock, so the arc grows like a clock hand.
        cv2.ellipse(view, _point(centre), (_px(radius), _px(radius)), 0, -90, -90 + 360 * progress, color,
                    RETICLE_ARC_PX, cv2.LINE_AA, SHIFT)


def _label(view: np.ndarray, obj: SceneObject, centre: tuple[float, float], radius: float) -> None:
    """Label pill above the object, a little right of the reticle, with a thin line down to the reticle's rim."""
    h, w = view.shape[:2]
    x1, y1, x2, _ = obj.bbox
    text = obj.label[:1].upper() + obj.label[1:]
    patch, alpha = _label_pill(f"{text} · destination" if obj.confirmed else text)
    ph, pw = alpha.shape[:2]
    # Clamp the pill's corner so the whole pill stays inside the frame.
    wanted_x = centre[0] + PILL_SHIFT_FRAC * (x2 - x1) - pw / 2
    px = int(np.clip(wanted_x, EDGE_MARGIN, max(EDGE_MARGIN, w - pw - EDGE_MARGIN)))
    py = int(np.clip(y1 - PILL_RISE - ph, EDGE_MARGIN, max(EDGE_MARGIN, h - ph - EDGE_MARGIN)))
    foot = np.array([px + PILL_FOOT_FRAC * pw, py + ph - 1.0])  # where the leader line leaves the pill
    toward = foot - centre
    reach = float(np.linalg.norm(toward))
    if reach > radius:  # the line stops at the circle's rim instead of crossing the reticle
        _polylines(view, [np.array([foot, centre + toward / reach * radius])], False, _bgr(CYAN_RGB), 1)
    _paste(view, patch, alpha, px, py)


def _paste(view: np.ndarray, patch: np.ndarray, alpha: np.ndarray, x: int, y: int) -> None:
    """Blend a small pre-drawn patch (float BGR + 0..1 alpha) onto `view`, cut off at the frame's edges."""
    h, w = view.shape[:2]
    x1, y1, x2, y2 = max(x, 0), max(y, 0), min(x + patch.shape[1], w), min(y + patch.shape[0], h)
    if x1 >= x2 or y1 >= y2:
        return
    part, a = patch[y1 - y:y2 - y, x1 - x:x2 - x], alpha[y1 - y:y2 - y, x1 - x:x2 - x]
    roi = view[y1:y2, x1:x2]
    roi[:] = (roi * (1 - a) + part * a).astype(np.uint8)


def _cursor(view: np.ndarray, xy: tuple[float, float]) -> None:
    """Gaze cursor: a ring and a centre dot (its soft glow was added earlier through the glow layer)."""
    centre = _point(xy)
    cv2.circle(view, centre, _px(CURSOR_R), _bgr(CYAN_RGB), CURSOR_PX, cv2.LINE_AA, SHIFT)
    cv2.circle(view, centre, _px(CURSOR_DOT_PX), _bgr(WHITE_RGB), -1, cv2.LINE_AA, SHIFT)


# ---------------------------------------------------------------- text, bars and the label pill (Pillow, cached)

@functools.lru_cache(maxsize=32)
def _font(face: str, size: int) -> ImageFont.ImageFont | ImageFont.FreeTypeFont:
    path, index = FONT_FILES.get(face, ("", 0))
    try:
        if Path(path).is_file():
            return ImageFont.truetype(path, size, index=index)
    except OSError:
        pass  # unreadable or damaged font file: fall through to the built-in font below
    return ImageFont.load_default(size)


def _supersampled(mode: str, size: tuple[int, int], background, paint: Callable[[ImageDraw.ImageDraw, int], None]
                  ) -> Image.Image:
    """Run `paint(draw, s)` on a canvas s times too big, then shrink it: smooth edges for Pillow's shapes."""
    big = Image.new(mode, (size[0] * SUPERSAMPLE, size[1] * SUPERSAMPLE), background)
    paint(ImageDraw.Draw(big), SUPERSAMPLE)
    return big.resize(size, Image.LANCZOS)


def _frozen_bgr(picture: Image.Image) -> np.ndarray:
    """Pillow RGB image -> read-only BGR array (read-only because the cache hands the same array out again)."""
    array = np.ascontiguousarray(np.asarray(picture.convert("RGB"))[:, :, ::-1])
    array.setflags(write=False)
    return array


def _fit(text: str, face, max_width: float) -> str:
    """`text`, shortened with an ellipsis until it is at most `max_width` pixels wide ("" if nothing fits)."""
    if face.getlength(text) <= max_width:
        return text
    for end in range(len(text) - 1, 0, -1):
        short = text[:end].rstrip() + "…"
        if face.getlength(short) <= max_width:
            return short
    return ""


@functools.lru_cache(maxsize=8)
def _top_bar(width: int, left: str, right: str) -> np.ndarray:
    bar = Image.new("RGB", (width, TOP_BAR_H), BAR_RGB)
    draw = ImageDraw.Draw(bar)
    middle = TOP_BAR_H // 2
    face = _font("bold", TITLE_FONT_PX)
    x = float(BAR_MARGIN)
    for letter in left:  # one letter at a time, to put a little extra space between them
        draw.text((x, middle), letter, font=face, fill=WHITE_RGB, anchor="lm")
        x += face.getlength(letter) + TITLE_TRACKING_PX
    small = _font("demi", SUBTITLE_FONT_PX)
    right = _fit(right, small, width - BAR_MARGIN - x - TEXT_CLEARANCE)
    draw.text((width - BAR_MARGIN, middle), right, font=small, fill=TITLE_GREY_RGB, anchor="rm")
    return _frozen_bgr(bar)


def _stop_rect_in_bar(width: int) -> tuple[int, int, int, int]:
    """STOP button (x1, y1, x2, y2) inside the bottom bar; on a very narrow frame it shrinks to stay visible."""
    x2 = max(width - BAR_MARGIN, min(width, STOP_W))
    x1 = max(0, x2 - STOP_W)
    y1 = (BOTTOM_BAR_H - STOP_H) // 2
    return x1, y1, x2, y1 + STOP_H


def _paint_route_icon(draw: ImageDraw.ImageDraw, s: int) -> None:
    """Small icon: two map pins joined by a dashed path. Coordinates are bar pixels times `s`."""
    cyan = CYAN_RGB

    def pin(cx: float, cy: float, r: float) -> None:
        draw.polygon([((cx - 0.92 * r) * s, (cy + 0.4 * r) * s), ((cx + 0.92 * r) * s, (cy + 0.4 * r) * s),
                      (cx * s, (cy + 2.1 * r) * s)], fill=cyan)
        draw.ellipse(((cx - r) * s, (cy - r) * s, (cx + r) * s, (cy + r) * s), fill=cyan)
        hole = 0.42 * r
        draw.ellipse(((cx - hole) * s, (cy - hole) * s, (cx + hole) * s, (cy + hole) * s), fill=BAR_RGB)

    left, top = BAR_MARGIN, (BOTTOM_BAR_H - 44) // 2
    pin(left + 8, top + 28, 5.5)
    pin(left + 39, top + 9, 7.5)
    # Dashed S-curve from the small pin's tip to the big pin's tip (a cubic Bezier, drawn as short pieces).
    p0, p1, p2, p3 = (left + 12, top + 41), (left + 30, top + 46), (left + 20, top + 27), (left + 36, top + 27)
    for start in (0.0, 0.26, 0.52, 0.78):
        piece = []
        for t in np.linspace(start, start + 0.16, 5):
            b = [(1 - t) ** 3, 3 * (1 - t) ** 2 * t, 3 * (1 - t) * t ** 2, t ** 3]
            piece.append((sum(w * p[0] for w, p in zip(b, (p0, p1, p2, p3))) * s,
                          sum(w * p[1] for w, p in zip(b, (p0, p1, p2, p3))) * s))
        draw.line(piece, fill=cyan, width=2 * s, joint="curve")


@functools.lru_cache(maxsize=8)
def _bottom_bar_base(width: int, mode: str) -> tuple[Image.Image, int]:
    """Everything in the bottom bar except the status line, and the x where the status line starts."""
    x1, y1, x2, y2 = _stop_rect_in_bar(width)
    middle = BOTTOM_BAR_H // 2
    face = _font("demi", MODE_FONT_PX)
    mode = _fit(mode, face, x1 - TEXT_CLEARANCE - MODE_X)
    divider_x = MODE_X + int(face.getlength(mode)) + DIVIDER_GAP

    def shapes(draw: ImageDraw.ImageDraw, s: int) -> None:
        _paint_route_icon(draw, s)
        if divider_x < x1 - TEXT_CLEARANCE:
            draw.line((divider_x * s, DIVIDER_INSET * s, divider_x * s, (BOTTOM_BAR_H - DIVIDER_INSET) * s),
                      fill=DIVIDER_RGB, width=s)
        # The button is painted last, so nothing in the bar can ever cover it (C9).
        draw.rounded_rectangle((x1 * s, y1 * s, x2 * s - 1, y2 * s - 1), radius=(STOP_H // 2) * s, fill=STOP_RGB)
        sq_x, sq_y = x1 + STOP_SQUARE_X, middle - STOP_SQUARE // 2
        draw.rounded_rectangle((sq_x * s, sq_y * s, (sq_x + STOP_SQUARE) * s, (sq_y + STOP_SQUARE) * s),
                               radius=2 * s, fill=WHITE_RGB)

    bar = _supersampled("RGB", (width, BOTTOM_BAR_H), BAR_RGB, shapes)
    draw = ImageDraw.Draw(bar)
    draw.text((MODE_X, middle), mode, font=face, fill=WHITE_RGB, anchor="lm")
    draw.text((x1 + STOP_TEXT_X, middle), "STOP", font=_font("bold", STOP_FONT_PX), fill=WHITE_RGB, anchor="lm")
    return bar, divider_x + DIVIDER_GAP


@functools.lru_cache(maxsize=32)
def _bottom_bar(width: int, mode: str, status: str) -> np.ndarray:
    """Bottom bar with the status line. The status changes often, so only this cheap last step is redone."""
    base, status_x = _bottom_bar_base(width, mode)
    bar = base.copy()
    face = _font("medium", STATUS_FONT_PX)
    room = _stop_rect_in_bar(width)[0] - TEXT_CLEARANCE - status_x
    ImageDraw.Draw(bar).text((status_x, BOTTOM_BAR_H // 2), _fit(status, face, room), font=face,
                             fill=STATUS_GREY_RGB, anchor="lm")
    return _frozen_bgr(bar)


@functools.lru_cache(maxsize=64)
def _label_pill(text: str) -> tuple[np.ndarray, np.ndarray]:
    """Dark rounded pill with white text, as (float BGR patch, 0..1 alpha) ready for `_paste`."""
    face = _font("medium", LABEL_FONT_PX)
    width = int(math.ceil(face.getlength(text))) + 2 * PILL_PAD_X

    def shapes(draw: ImageDraw.ImageDraw, s: int) -> None:
        draw.rounded_rectangle((0, 0, width * s - 1, PILL_H * s - 1), radius=PILL_RADIUS * s,
                               fill=PILL_RGB + (PILL_OPACITY,))

    pill = _supersampled("RGBA", (width, PILL_H), PILL_RGB + (0,), shapes)
    ImageDraw.Draw(pill).text((width / 2, PILL_H / 2), text, font=face, fill=WHITE_RGB + (255,), anchor="mm")
    rgba = np.asarray(pill).astype(np.float32)
    patch, alpha = np.ascontiguousarray(rgba[:, :, 2::-1]), rgba[:, :, 3:4] / 255
    patch.setflags(write=False)
    alpha.setflags(write=False)
    return patch, alpha


# ---------------------------------------------------------------- floating chevrons

def _guide_line(guide) -> np.ndarray:
    """The chevron's centre line (arm end, tip, arm end) in frame pixels, rotated to point along the route."""
    arm_x, arm_y = GUIDE_ARM
    local = np.array([[-arm_x, arm_y], [0.0, -arm_y], [arm_x, arm_y]]) * guide.size
    c, s = math.cos(guide.angle), math.sin(guide.angle)
    # Positive angle turns an "up" chevron to the left; y grows downward on screen.
    rotated = np.stack([local[:, 0] * c + local[:, 1] * s, -local[:, 0] * s + local[:, 1] * c], axis=1)
    return rotated + np.asarray(guide.center)


def _guide_shadow(view: np.ndarray, guide) -> None:
    """Soft flattened shadow on the floor under the chevron, blended only inside a small box around it."""
    h, w = view.shape[:2]
    cx, cy = guide.center[0], guide.center[1] + 0.95 * guide.size
    ax, ay = 0.42 * guide.size, 0.08 * guide.size
    x1, y1, x2, y2 = int(cx - ax - 2), int(cy - ay - 2), int(cx + ax + 3), int(cy + ay + 3)
    x1, y1, x2, y2 = max(x1, 0), max(y1, 0), min(x2, w), min(y2, h)
    if x1 >= x2 or y1 >= y2:
        return
    mask = np.zeros((y2 - y1, x2 - x1), np.uint8)
    cv2.ellipse(mask, (int(cx - x1), int(cy - y1)), (max(1, int(ax)), max(1, int(ay))), 0, 0, 360, 255, -1,
                cv2.LINE_AA)
    mask = cv2.GaussianBlur(mask, (0, 0), max(1.0, ay / 2))
    a = (mask.astype(np.float32) / 255 * GUIDE_SHADOW_ALPHA)[:, :, None]
    roi = view[y1:y2, x1:x2]
    roi[:] = (roi * (1 - a)).astype(np.uint8)


def _draw_guides(view: np.ndarray, guides, clock: float, label: str | None) -> None:
    """Far chevrons first, so nearer ones overlap them. One soft highlight drifts along the row."""
    count = len(guides)
    flow = (clock * GUIDE_FLOW_PER_S) % (count + 1.5)  # the extra half-chevron of quiet before it starts again
    for guide in sorted(guides, key=lambda g: -g.depth):
        line = _guide_line(guide)
        stroke = max(4, int(round(GUIDE_STROKE * guide.size)))
        rim = max(2, int(round(GUIDE_RIM * guide.size)))
        side = line + np.array(GUIDE_DEPTH) * guide.size
        lit = max(0.0, 1.0 - abs(flow - guide.order))  # 0..1, smooth: a gentle glow passing by, never a blink
        face = tuple(int(f + (g - f) * lit) for f, g in zip(GUIDE_FACE_RGB, GUIDE_LIT_RGB))
        _guide_shadow(view, guide)
        _polylines(view, [side], False, _bgr(GUIDE_SIDE_RGB), stroke + 2 * rim)
        _polylines(view, [line], False, _bgr(CYAN_RGB), stroke + 2 * rim)
        _polylines(view, [line], False, _bgr(face), stroke)
    if label:
        far = max(guides, key=lambda g: g.depth)
        patch, alpha = _label_pill(label)
        top = _guide_line(far)[:, 1].min()
        x = int(far.center[0] - patch.shape[1] / 2)
        y = int(top - GUIDE_LABEL_GAP - patch.shape[0])
        _paste(view, patch, alpha, min(max(x, EDGE_MARGIN), view.shape[1] - patch.shape[1] - EDGE_MARGIN),
               max(y, EDGE_MARGIN))
