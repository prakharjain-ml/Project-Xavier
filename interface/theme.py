"""Xavier design system: the one place every screen gets its colours, type, shapes and motion from.

Screens draw on a Pillow RGB image with these helpers, then hand OpenCV a BGR array with `to_bgr()`. Shapes are
drawn 3x too big and shrunk (smooth edges) and cached, so a whole screen redraws in a few milliseconds.

Tokens follow the ui-ux-pro-max recommendation for a healthcare control product: calm cyan on deep navy,
legible system type, one elevation, restrained motion. Text/background pairs are >= 4.5:1. Red is reserved for
STOP / emergency only (the HUD tests check that red appears nowhere else); warnings are amber.
"""

from __future__ import annotations

import functools
import math
import os
from typing import Iterable

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

RGB = tuple[int, int, int]

# ---- Colour tokens (R, G, B)
BG: RGB = (11, 15, 20)            # app background
SURFACE: RGB = (18, 24, 33)       # cards, bars
SURFACE_2: RGB = (27, 35, 48)     # raised: chips, tracks, hovered cards
BORDER: RGB = (40, 52, 70)        # hairlines
TEXT: RGB = (230, 237, 243)       # primary text (15.6:1 on BG)
MUTED: RGB = (139, 152, 169)      # secondary text (6.9:1 on BG)
FAINT: RGB = (92, 104, 122)       # hints, disabled
PRIMARY: RGB = (34, 211, 238)     # brand cyan: focus, progress, selection
PRIMARY_DIM: RGB = (14, 116, 144)
SUCCESS: RGB = (16, 185, 129)     # confirmed / ready
WARNING: RGB = (245, 158, 11)     # needs attention (never red: red means STOP)
DANGER: RGB = (239, 68, 68)       # STOP and emergency only
WHITE: RGB = (255, 255, 255)

# ---- Type: SF Pro (the macOS system face, variable weights); Avenir Next / Pillow default as fallbacks.
SF_PRO = "/System/Library/Fonts/SFNS.ttf"
SF_MONO = "/System/Library/Fonts/SFNSMono.ttf"
AVENIR = "/System/Library/Fonts/Avenir Next.ttc"
AVENIR_FACE = {"regular": 7, "medium": 5, "semibold": 2, "bold": 0, "heavy": 8}
WEIGHT_NAMES = {"regular": "Regular", "medium": "Medium", "semibold": "Semibold", "bold": "Bold", "heavy": "Heavy"}
SIZE_XS, SIZE_SM, SIZE_MD, SIZE_LG, SIZE_XL, SIZE_2XL, SIZE_3XL = 13, 15, 18, 24, 32, 44, 60

# ---- Shape and space (4 px grid)
SPACE = 8
RADIUS_SM, RADIUS_MD, RADIUS_LG = 10, 16, 24
SUPERSAMPLE = 3
SHADOW_BLUR, SHADOW_OFFSET, SHADOW_ALPHA = 18, 8, 110

# ---- Motion tokens (seconds). Respect a reduced-motion request: XAVIER_REDUCED_MOTION=1.
DUR_PRESS, DUR_STATE, DUR_ENTER = 0.15, 0.25, 0.40
REDUCED_MOTION = os.environ.get("XAVIER_REDUCED_MOTION") == "1"


# ================================================================ motion
def clamp01(t: float) -> float:
    return 0.0 if t <= 0 else 1.0 if t >= 1 else t


def ease_out(t: float) -> float:
    """Decelerate into place (things arriving)."""
    t = clamp01(t)
    return 1.0 if REDUCED_MOTION else 1 - (1 - t) ** 3


def ease_in_out(t: float) -> float:
    t = clamp01(t)
    return 1.0 if REDUCED_MOTION else t * t * (3 - 2 * t)


def spring(t: float) -> float:
    """Slight overshoot then settle: selection and confirmation feel physical, not linear."""
    t = clamp01(t)
    if REDUCED_MOTION:
        return 1.0
    return 1 - math.exp(-6.5 * t) * math.cos(9.0 * t)


def pulse(clock: float, period: float = 1.6) -> float:
    """0..1..0 breathing value for idle attention cues (calm: 1.6 s period)."""
    return 0.0 if REDUCED_MOTION else 0.5 - 0.5 * math.cos(2 * math.pi * clock / period)


def mix(a: RGB, b: RGB, t: float) -> RGB:
    t = clamp01(t)
    return tuple(int(round(x + (y - x) * t)) for x, y in zip(a, b))  # type: ignore[return-value]


# ================================================================ type
@functools.lru_cache(maxsize=128)
def font(size: int, weight: str = "regular", mono: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Cached font. A missing file falls back (Avenir, then Pillow's own), so a screen never crashes over a font."""
    try:
        face = ImageFont.truetype(SF_MONO if mono else SF_PRO, size)
        try:
            face.set_variation_by_name(WEIGHT_NAMES.get(weight, "Regular"))
        except (OSError, ValueError):  # not a variable font: keep its default weight
            pass
        return face
    except OSError:
        pass
    try:
        return ImageFont.truetype(AVENIR, size, index=AVENIR_FACE.get(weight, 7))
    except OSError:
        return ImageFont.load_default()


def text_size(s: str, size: int, weight: str = "regular", mono: bool = False) -> tuple[int, int]:
    left, top, right, bottom = font(size, weight, mono).getbbox(s)
    return right - left, bottom - top


def fit_text(s: str, size: int, weight: str, max_w: int) -> str:
    """Shorten with an ellipsis so the text never runs into its neighbour."""
    if text_size(s, size, weight)[0] <= max_w:
        return s
    while s and text_size(s + "…", size, weight)[0] > max_w:
        s = s[:-1]
    return (s + "…") if s else ""


def text(img: Image.Image, xy: tuple[float, float], s: str, size: int = SIZE_MD, weight: str = "regular",
         fill: RGB = TEXT, anchor: str = "la", mono: bool = False, max_w: int | None = None) -> None:
    """Draw text. anchor: Pillow anchors, e.g. 'la' left-ascender, 'mm' centred, 'rm' right-middle."""
    if max_w is not None:
        s = fit_text(s, size, weight, max_w)
    ImageDraw.Draw(img).text(xy, s, font=font(size, weight, mono), fill=fill, anchor=anchor)


def wrap(s: str, size: int, weight: str, max_w: int) -> list[str]:
    words, lines, line = s.split(), [], ""
    for word in words:
        trial = f"{line} {word}".strip()
        if text_size(trial, size, weight)[0] <= max_w or not line:
            line = trial
        else:
            lines.append(line)
            line = word
    return lines + ([line] if line else [])


# ================================================================ shapes (cached RGBA sprites)
@functools.lru_cache(maxsize=256)
def _rounded_sprite(w: int, h: int, radius: int, fill: RGB | None, outline: RGB | None, width: int,
                    alpha: int) -> Image.Image:
    s = SUPERSAMPLE
    big = Image.new("RGBA", (max(1, w * s), max(1, h * s)), (0, 0, 0, 0))
    ImageDraw.Draw(big).rounded_rectangle(
        (0, 0, w * s - 1, h * s - 1), radius=radius * s,
        fill=None if fill is None else (*fill, alpha),
        outline=None if outline is None else (*outline, alpha), width=width * s)
    return big.resize((max(1, w), max(1, h)), Image.LANCZOS)


@functools.lru_cache(maxsize=64)
def _shadow_sprite(w: int, h: int, radius: int) -> Image.Image:
    pad = SHADOW_BLUR * 2
    img = Image.new("RGBA", (w + 2 * pad, h + 2 * pad), (0, 0, 0, 0))
    ImageDraw.Draw(img).rounded_rectangle((pad, pad, pad + w, pad + h), radius=radius, fill=(0, 0, 0, SHADOW_ALPHA))
    return img.filter(ImageFilter.GaussianBlur(SHADOW_BLUR / 2))


def _paste(img: Image.Image, sprite: Image.Image, x: float, y: float) -> None:
    img.paste(sprite, (int(round(x)), int(round(y))), sprite)


def rounded(img: Image.Image, box: tuple[float, float, float, float], radius: int = RADIUS_MD,
            fill: RGB | None = SURFACE, outline: RGB | None = None, width: int = 1, alpha: int = 255) -> None:
    x1, y1, x2, y2 = (int(round(v)) for v in box)
    if x2 - x1 < 2 or y2 - y1 < 2:
        return
    radius = min(radius, (x2 - x1) // 2, (y2 - y1) // 2)
    _paste(img, _rounded_sprite(x2 - x1, y2 - y1, radius, fill, outline, width, alpha), x1, y1)


def panel(img: Image.Image, box: tuple[float, float, float, float], radius: int = RADIUS_LG, fill: RGB = SURFACE,
          border: RGB | None = BORDER, shadow: bool = True, alpha: int = 255) -> None:
    """A card: soft drop shadow, surface fill, 1 px hairline border."""
    x1, y1, x2, y2 = (int(round(v)) for v in box)
    if shadow and x2 - x1 > 2 and y2 - y1 > 2:
        sprite = _shadow_sprite(x2 - x1, y2 - y1, radius)
        _paste(img, sprite, x1 - SHADOW_BLUR * 2, y1 - SHADOW_BLUR * 2 + SHADOW_OFFSET)
    rounded(img, box, radius, fill, border, 1, alpha)


def pill(img: Image.Image, left: float, cy: float, label: str, fg: RGB = TEXT, bg: RGB = SURFACE_2,
         size: int = SIZE_SM, weight: str = "semibold", dot: RGB | None = None, border: RGB | None = None,
         height: int | None = None) -> float:
    """A rounded chip with optional status dot. Returns the x where it ends."""
    tw, _ = text_size(label, size, weight)
    h = height or size + 16
    pad = h // 2
    dot_w = (h // 3 + 8) if dot else 0
    w = tw + 2 * pad + dot_w
    rounded(img, (left, cy - h / 2, left + w, cy + h / 2), h // 2, bg, border)
    x = left + pad
    if dot:
        r = h // 6
        circle(img, (x + r, cy), r, dot)
        x += dot_w
    text(img, (x, cy), label, size, weight, fg, anchor="lm")
    return left + w


def pill_width(label: str, size: int = SIZE_SM, weight: str = "semibold", dot: bool = False,
               height: int | None = None) -> float:
    h = height or size + 16
    return text_size(label, size, weight)[0] + 2 * (h // 2) + ((h // 3 + 8) if dot else 0)


@functools.lru_cache(maxsize=256)
def _circle_sprite(r: float, fill: RGB | None, outline: RGB | None, width: int) -> Image.Image:
    s = SUPERSAMPLE
    d = int(math.ceil(2 * r + 2 * width + 2))
    big = Image.new("RGBA", (d * s, d * s), (0, 0, 0, 0))
    c = d * s / 2
    ImageDraw.Draw(big).ellipse((c - r * s, c - r * s, c + r * s, c + r * s),
                                fill=None if fill is None else (*fill, 255),
                                outline=None if outline is None else (*outline, 255), width=width * s)
    return big.resize((d, d), Image.LANCZOS)


def circle(img: Image.Image, center: tuple[float, float], r: float, fill: RGB | None = PRIMARY,
           outline: RGB | None = None, width: int = 2) -> None:
    if r <= 0:
        return
    sprite = _circle_sprite(round(r * 2) / 2, fill, outline, width)
    _paste(img, sprite, center[0] - sprite.width / 2, center[1] - sprite.height / 2)


@functools.lru_cache(maxsize=512)
def _ring_sprite(r: int, width: int, frac_pct: int, color: RGB, track: RGB | None) -> Image.Image:
    s = SUPERSAMPLE
    d = 2 * r + 2 * width + 4
    big = Image.new("RGBA", (d * s, d * s), (0, 0, 0, 0))
    draw = ImageDraw.Draw(big)
    c, rr = d * s / 2, r * s
    bbox = (c - rr, c - rr, c + rr, c + rr)
    if track is not None:
        draw.ellipse(bbox, outline=(*track, 255), width=width * s)
    if frac_pct >= 100:
        draw.ellipse(bbox, outline=(*color, 255), width=width * s)
    elif frac_pct > 0:
        draw.arc(bbox, -90, -90 + 360 * frac_pct / 100, fill=(*color, 255), width=width * s)
    return big.resize((d, d), Image.LANCZOS)


def ring(img: Image.Image, center: tuple[float, float], r: float, frac: float, width: int = 4,
         color: RGB = PRIMARY, track: RGB | None = SURFACE_2) -> None:
    """Progress ring starting at 12 o'clock, clockwise."""
    if r < 1:
        return
    sprite = _ring_sprite(int(r), width, int(round(clamp01(frac) * 100)), color, track)
    _paste(img, sprite, center[0] - sprite.width / 2, center[1] - sprite.height / 2)


def progress(img: Image.Image, box: tuple[float, float, float, float], frac: float, color: RGB = PRIMARY,
             track: RGB = SURFACE_2) -> None:
    x1, y1, x2, y2 = box
    r = int((y2 - y1) / 2)
    rounded(img, box, r, track)
    filled = x1 + (x2 - x1) * clamp01(frac)
    if filled - x1 >= 2 * r:
        rounded(img, (x1, y1, filled, y2), r, color)
    elif frac > 0:
        circle(img, (x1 + r, (y1 + y2) / 2), r, color)


def steps(img: Image.Image, center: tuple[float, float], total: int, current: int, gap: int = 14) -> None:
    """Step indicator: done and current = cyan (current is a wide capsule), upcoming = dim dots."""
    widths = [32 if i == current else 10 for i in range(total)]
    x = center[0] - (sum(widths) + gap * (total - 1)) / 2
    for i, w in enumerate(widths):
        color = PRIMARY if i <= current else SURFACE_2
        rounded(img, (x, center[1] - 5, x + w, center[1] + 5), 5, color)
        x += w + gap


# ================================================================ icons (vector, one stroke weight, no emoji)
@functools.lru_cache(maxsize=256)
def _icon_sprite(name: str, size: int, color: RGB, stroke: float) -> Image.Image:
    s = SUPERSAMPLE
    d = size * s
    big = Image.new("RGBA", (d, d), (0, 0, 0, 0))
    g = ImageDraw.Draw(big)
    w = max(1, int(stroke * s * size / 24))
    c = (*color, 255)
    u = d / 24.0  # icons are designed on a 24-unit grid

    def pts(*xy):
        return [(x * u, y * u) for x, y in xy]

    def box(x1, y1, x2, y2):
        return (x1 * u, y1 * u, x2 * u, y2 * u)

    if name == "eye":
        g.arc(box(2, 5, 22, 19), 200, 340, fill=c, width=w)
        g.arc(box(2, 5, 22, 19), 20, 160, fill=c, width=w)
        g.ellipse(box(8.5, 8.5, 15.5, 15.5), outline=c, width=w)
    elif name == "blink":
        g.arc(box(2, 1, 22, 15), 20, 160, fill=c, width=w)
        for x in (6, 12, 18):
            g.line(pts((x, 15), (x + (x - 12) * 0.25, 19)), fill=c, width=w)
    elif name == "jaw":
        g.line(pts((3, 12), (7, 12), (9, 6), (12, 18), (15, 8), (17, 12), (21, 12)), fill=c, width=w, joint="curve")
    elif name == "pulse":
        g.line(pts((2, 13), (6, 13), (8, 9), (11, 17), (14, 5), (16, 13), (22, 13)), fill=c, width=w, joint="curve")
    elif name == "wifi":
        for r in (9, 6, 3):
            g.arc(box(12 - r, 18 - r, 12 + r, 18 + r), 225, 315, fill=c, width=w)
        g.ellipse(box(10.8, 17.8, 13.2, 20.2), fill=c)
    elif name == "camera":
        g.rounded_rectangle(box(2, 7, 22, 19), radius=3 * u, outline=c, width=w)
        g.ellipse(box(8.5, 9.5, 15.5, 16.5), outline=c, width=w)
        g.line(pts((8, 7), (9.5, 4.5), (14.5, 4.5), (16, 7)), fill=c, width=w)
    elif name == "motor":
        g.ellipse(box(3, 3, 21, 21), outline=c, width=w)
        g.ellipse(box(9.5, 9.5, 14.5, 14.5), outline=c, width=w)
        for a in range(0, 360, 60):
            ca, sa = math.cos(math.radians(a)), math.sin(math.radians(a))
            g.line(box(12 + 3 * ca, 12 + 3 * sa, 12 + 8 * ca, 12 + 8 * sa), fill=c, width=w)
    elif name == "stop":
        g.rounded_rectangle(box(6, 6, 18, 18), radius=2 * u, fill=c)
    elif name == "check":
        g.line(pts((5, 12.5), (10, 17.5), (19, 7)), fill=c, width=int(w * 1.2), joint="curve")
    elif name == "alert":
        g.line(pts((12, 3), (22, 20), (2, 20), (12, 3)), fill=c, width=w, joint="curve")
        g.line(pts((12, 9), (12, 14)), fill=c, width=w)
        g.ellipse(box(11, 16, 13, 18), fill=c)
    elif name == "play":
        g.polygon(pts((8, 5), (19, 12), (8, 19)), fill=c)
    elif name == "keyboard":
        g.rounded_rectangle(box(2, 6, 22, 18), radius=2.5 * u, outline=c, width=w)
        for x in (6, 10, 14, 18):
            g.ellipse(box(x - 0.9, 9.1, x + 0.9, 10.9), fill=c)
        g.line(pts((7, 14.5), (17, 14.5)), fill=c, width=w)
    elif name == "route":
        g.line(pts((5, 20), (5, 14), (12, 10), (17, 7.5)), fill=c, width=w, joint="curve")
        g.ellipse(box(16, 3, 22, 9), outline=c, width=w)
        g.ellipse(box(3, 18, 7, 22), fill=c)
    elif name == "chevron":
        g.line(pts((9, 5), (16, 12), (9, 19)), fill=c, width=w, joint="curve")
    elif name == "target":
        g.ellipse(box(3, 3, 21, 21), outline=c, width=w)
        g.ellipse(box(8, 8, 16, 16), outline=c, width=w)
        g.ellipse(box(11, 11, 13, 13), fill=c)
    elif name == "arrows":
        g.polygon(pts((12, 2), (15, 6), (9, 6)), fill=c)
        g.polygon(pts((12, 22), (15, 18), (9, 18)), fill=c)
        g.polygon(pts((2, 12), (6, 9), (6, 15)), fill=c)
        g.polygon(pts((22, 12), (18, 9), (18, 15)), fill=c)
    else:  # unknown name: a neutral dot, never a crash
        g.ellipse(box(9, 9, 15, 15), fill=c)
    return big.resize((size, size), Image.LANCZOS)


def icon(img: Image.Image, name: str, center: tuple[float, float], size: int = 24, color: RGB = TEXT,
         stroke: float = 2.0) -> None:
    """Line icons on a 24-unit grid, one stroke weight: eye, blink, jaw, pulse, wifi, camera, motor, stop, check,
    alert, play, keyboard, route, chevron, target, arrows."""
    sprite = _icon_sprite(name, int(size), color, stroke)
    _paste(img, sprite, center[0] - size / 2, center[1] - size / 2)


# ================================================================ canvases
@functools.lru_cache(maxsize=8)
def _background(w: int, h: int) -> Image.Image:
    """Deep navy with a faint cyan glow at the top centre: depth without noise."""
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    d = np.sqrt(((xx - w / 2) / (w * 0.75)) ** 2 + ((yy + h * 0.2) / (h * 0.95)) ** 2)
    glow = np.clip(1.0 - d, 0, 1) ** 2
    base = np.array(BG, np.float32)
    tint = np.array((14, 44, 58), np.float32)
    rgb = base + glow[..., None] * (tint - base)
    return Image.fromarray(np.clip(rgb, 0, 255).astype(np.uint8), "RGB")


def canvas(w: int, h: int) -> Image.Image:
    """A fresh screen-sized image with the app background (cached base, copied per frame)."""
    return _background(w, h).copy()


def to_bgr(img: Image.Image) -> np.ndarray:
    """Pillow -> OpenCV. Pillow writes BGR bytes directly: 0.6 ms for a full screen, vs 8.5 ms with a numpy flip.
    The result is a fresh writable array (callers may draw on it)."""
    rgb = img if img.mode == "RGB" else img.convert("RGB")
    return np.frombuffer(rgb.tobytes("raw", "BGR"), np.uint8).reshape(rgb.height, rgb.width, 3).copy()


def from_bgr(array: np.ndarray) -> Image.Image:
    return Image.fromarray(np.ascontiguousarray(array[:, :, ::-1]), "RGB")


def brand(img: Image.Image, xy: tuple[float, float], size: int = SIZE_MD, color: RGB = TEXT) -> float:
    """Logo mark (cyan ring + dot) and the XAVIER wordmark, vertically centred on xy. Returns the end x."""
    x, y = xy
    r = size * 0.5
    ring(img, (x + r, y), r, 1.0, max(2, size // 8), PRIMARY, None)
    circle(img, (x + r, y), r * 0.34, PRIMARY)
    tx = x + 2 * r + size * 0.6
    spacing = size * 0.14  # wide tracking for the wordmark
    for ch in "XAVIER":
        text(img, (tx, y), ch, size, "bold", color, anchor="lm")
        tx += text_size(ch, size, "bold")[0] + spacing
    return tx - spacing


def key_hints(img: Image.Image, right: float, cy: float, hints: Iterable[tuple[str, str]],
              size: int = SIZE_SM) -> float:
    """Right-aligned keyboard hints: [KEY] label  [KEY] label ... Returns the x where the hints start."""
    x = right
    for key, label in reversed(list(hints)):
        lw, _ = text_size(label, size, "medium")
        text(img, (x, cy), label, size, "medium", MUTED, anchor="rm")
        x -= lw + 10
        kw = max(30, text_size(key, size - 2, "semibold")[0] + 18)
        rounded(img, (x - kw, cy - 14, x, cy + 14), 7, SURFACE_2, BORDER)
        text(img, (x - kw / 2, cy), key, size - 2, "semibold", TEXT, anchor="mm")
        x -= kw + 24
    return x
