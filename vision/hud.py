"""Futuristic HUD drawing for the navigation preview: blue-gradient floor path with glow, target ring, corner
brackets, smooth fonts (Pillow + macOS fonts) and a stats panel. Palette from the team's design reference.
Pure drawing: images in, new images out (inputs are never modified)."""

from __future__ import annotations

import functools
import math
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

PALETTE = {"navy": "#03195b", "royal": "#0b2cb1", "blue": "#1951fc", "sky": "#3781fc", "ice": "#cbe9fd"}
FONT_FILES = {"text": "/System/Library/Fonts/Avenir Next.ttc",
              "num": "/System/Library/Fonts/Supplemental/DIN Alternate Bold.ttf"}
_font_cache: dict = {}


def rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def bgr(hex_color: str) -> tuple[int, int, int]:
    r, g, b = rgb(hex_color)
    return b, g, r


def mix(a: str, b: str, t: float) -> tuple[int, int, int]:
    """BGR colour t of the way from hex a to hex b."""
    ca, cb = np.array(bgr(a), float), np.array(bgr(b), float)
    return tuple(int(v) for v in ca + (cb - ca) * min(1.0, max(0.0, t)))


def font(kind: str, size: int):
    key = (kind, size)
    if key not in _font_cache:
        path = FONT_FILES.get(kind, "")
        _font_cache[key] = ImageFont.truetype(path, size) if Path(path).exists() else ImageFont.load_default()
    return _font_cache[key]


class TextLayer:
    """Collect text for one frame, then draw it all in a single Pillow pass (anti-aliased, modern fonts)."""

    def __init__(self) -> None:
        self.items: list = []

    def add(self, text: str, xy, size: int, color: str = PALETTE["ice"], kind: str = "text", anchor: str = "la"):
        self.items.append((text, xy, size, color, kind, anchor))

    def render(self, img: np.ndarray) -> np.ndarray:
        if not self.items:
            return img.copy()
        pil = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
        draw = ImageDraw.Draw(pil)
        for text, xy, size, color, kind, anchor in self.items:
            draw.text(xy, text, font=font(kind, size), fill=rgb(color), anchor=anchor)
        return cv2.cvtColor(np.asarray(pil), cv2.COLOR_RGB2BGR)


def _densify(path, step=0.08):
    pts = []
    for a, b in zip(path, path[1:]):
        n = max(2, int(math.dist(a, b) / step))
        pts += [(a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t) for t in np.linspace(0, 1, n, endpoint=False)]
    return np.array(pts + [path[-1]], float)


CHEVRON_GAP_M = 0.5  # one direction arrow every half metre of path
OFFSCREEN_PX = 20000  # floor points next to the chair project far below the frame; keep them in OpenCV's range


def draw_floor_path(img: np.ndarray, path, project, half_width: float = 0.3, phase: float = 0.0) -> np.ndarray:
    """Ribbon as wide as the chair along the floor path: faint royal blue at the chair -> bright ice blue at the
    goal, with a blue halo, bright edges and arrows that flow toward the goal as `phase` (metres) grows."""
    if path is None or len(path) < 2:
        return img.copy()
    pts = _densify(path)
    heading = np.gradient(pts, axis=0)
    heading /= np.linalg.norm(heading, axis=1, keepdims=True) + 1e-9
    normal = np.stack([-heading[:, 1], heading[:, 0]], axis=1)  # unit vector pointing to the path's left
    left, right = project(pts + normal * half_width), project(pts - normal * half_width)
    h, w = img.shape[:2]
    color, alpha = np.zeros_like(img), np.zeros((h, w), np.uint8)
    last = max(1, len(pts) - 2)
    for i in range(len(pts) - 1):
        quad = np.array([left[i], left[i + 1], right[i + 1], right[i]])
        if np.isnan(quad).any():
            continue
        t = i / last  # 0 at the chair, 1 at the goal
        quad = np.clip(quad, -OFFSCREEN_PX, OFFSCREEN_PX).astype(np.int32)
        cv2.fillConvexPoly(color, quad, mix(PALETTE["royal"], PALETTE["ice"], t))
        cv2.fillConvexPoly(alpha, quad, int(255 * (0.3 + 0.4 * t)))  # more see-through near the chair
    x, y, bw, bh = cv2.boundingRect(alpha)
    if bw == 0:
        return img.copy()
    out = img.copy()
    roi = (slice(y, y + bh), slice(x, x + bw))  # blend only where the ribbon is (keeps this fast)
    a = alpha[roi][..., None].astype(np.float32) / 255
    out[roi] = (img[roi] * (1 - a) + color[roi] * a).astype(np.uint8)
    # Halo: blur the ribbon's shape at quarter size (cheap), tint it blue, add it on top.
    small = cv2.GaussianBlur(cv2.resize(alpha, (w // 4, h // 4)), (0, 0), 5).astype(np.float32) / 255
    halo = (small[..., None] * np.array(bgr(PALETTE["blue"]), np.float32) * 0.6).astype(np.uint8)
    out = cv2.add(out, cv2.resize(halo, (w, h)))
    for edge in (left, right):
        line = edge[~np.isnan(edge).any(axis=1)]
        cv2.polylines(out, [np.clip(line, -OFFSCREEN_PX, OFFSCREEN_PX).astype(np.int32)], False,
                      bgr(PALETTE["ice"]), 2, cv2.LINE_AA)
    along = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(pts, axis=0), axis=1))])  # metres from chair
    for s in np.arange(CHEVRON_GAP_M + phase % CHEVRON_GAP_M, along[-1] - 0.15, CHEVRON_GAP_M):
        i = int(np.searchsorted(along, s))
        wing = normal[i] * half_width * 0.55
        arrow = project(np.array([pts[i] + wing, pts[i] + heading[i] * 0.14, pts[i] - wing]))
        if not np.isnan(arrow).any():
            cv2.polylines(out, [arrow.astype(np.int32)], False, bgr(PALETTE["ice"]), 3, cv2.LINE_AA)
    return out


def draw_ground_ring(img: np.ndarray, center, project, radius: float = 0.35) -> np.ndarray:
    """Neon ring on the floor where the chair will stop (wide blue stroke under a thin ice stroke)."""
    angles = np.linspace(0, 2 * math.pi, 64)
    ring = project(np.stack([center[0] + radius * np.cos(angles), center[1] + radius * np.sin(angles)], axis=1))
    ring = ring[~np.isnan(ring).any(axis=1)]
    out = img.copy()
    if len(ring) < 3:
        return out
    ring = np.clip(ring, -OFFSCREEN_PX, OFFSCREEN_PX).astype(np.int32)
    cv2.polylines(out, [ring], True, bgr(PALETTE["blue"]), 9, cv2.LINE_AA)
    cv2.polylines(out, [ring], True, bgr(PALETTE["ice"]), 3, cv2.LINE_AA)
    return out


def corner_box(img: np.ndarray, box, color: str, thickness: int = 3, glow: bool = False) -> np.ndarray:
    """Four corner brackets instead of a full rectangle (lighter, more 'HUD'). glow adds a blue outline."""
    x1, y1, x2, y2 = map(int, box)
    arm = max(12, int(min(x2 - x1, y2 - y1) * 0.18))
    out = img.copy()
    strokes = ([(bgr(PALETTE["blue"]), thickness + 6)] if glow else []) + [(bgr(color), thickness)]
    for stroke_color, width in strokes:
        for (cx, cy), (dx, dy) in (((x1, y1), (1, 1)), ((x2, y1), (-1, 1)), ((x1, y2), (1, -1)), ((x2, y2), (-1, -1))):
            cv2.line(out, (cx, cy), (cx + dx * arm, cy), stroke_color, width, cv2.LINE_AA)
            cv2.line(out, (cx, cy), (cx, cy + dy * arm), stroke_color, width, cv2.LINE_AA)
    return out


@functools.lru_cache(maxsize=4)
def _panel_background(height: int, width: int) -> Image.Image:
    """Navy-to-near-black vertical gradient (built once per size)."""
    top, bottom = np.array(rgb(PALETTE["navy"]), float), np.array((4, 6, 18), float)
    grad = (top + (bottom - top) * np.linspace(0, 1, height)[:, None]).astype(np.uint8)
    return Image.fromarray(np.repeat(grad[:, None, :], width, axis=1))


def side_panel(height: int, width: int, stats: dict) -> np.ndarray:
    """Stats panel: navy-to-black gradient, section labels, big command, wheel bars, numbers."""
    pil = _panel_background(height, width).copy()
    d = ImageDraw.Draw(pil)
    ice, sky, blue = rgb(PALETTE["ice"]), rgb(PALETTE["sky"]), rgb(PALETTE["blue"])
    y = 28
    d.text((28, y), "XAVIER  //  NAVIGATION", font=font("text", 20), fill=sky)
    y += 46
    for title, value in stats.get("sections", []):
        d.text((28, y), title.upper(), font=font("text", 15), fill=sky)
        d.text((28, y + 20), value, font=font("num", 30), fill=ice)
        y += 72
    d.text((28, y), "MOTOR COMMAND", font=font("text", 15), fill=sky)
    d.text((28, y + 22), stats.get("command", "-"), font=font("num", 40), fill=ice)
    y += 82
    for name, speed in (("L", stats.get("left", 0)), ("R", stats.get("right", 0))):
        d.text((28, y), name, font=font("num", 22), fill=sky)
        x0, x1, mid = 60, width - 30, (60 + width - 30) // 2
        d.rounded_rectangle((x0, y + 4, x1, y + 22), radius=9, outline=blue, width=2)
        span = int((x1 - mid) * min(1.0, abs(speed) / 150))
        if span:
            a, b = (mid, mid + span) if speed > 0 else (mid - span, mid)
            d.rounded_rectangle((a, y + 6, b, y + 20), radius=7, fill=ice)
        y += 36
    d.text((28, height - 34), stats.get("footer", ""), font=font("text", 13), fill=sky)
    return cv2.cvtColor(np.asarray(pil), cv2.COLOR_RGB2BGR)
