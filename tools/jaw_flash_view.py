"""Look of the headset test (tools/jaw_flash.py), drawn with the app theme. Pure: probe values in, image out.

Layout: header; a big status disc on the left (idle ring, or a filled check while a clench flashes the screen
white); the stage checklist (the first amber row is where the chain is broken); the live level meter with the
threshold tick and one bar per channel; key hints.
"""

from __future__ import annotations

from PIL import Image

from interface import theme as t

STAGE_NAMES = ("Board", "Data", "Signal", "Level", "Clench")
LIGHT_SURFACE = (240, 243, 246)          # cards while the screen is flashed white
INK_LIGHT, MUTED_LIGHT = (20, 24, 30), (90, 100, 115)


def _rows(lines: list[tuple[str, bool]]) -> list[tuple[str, str, bool]]:
    """'2 DATA    250 samples/s ...' -> ('Data', '250 samples/s ...', ok)."""
    rows = []
    for (text, ok), name in zip(lines, STAGE_NAMES):
        parts = text.split(None, 2)
        rows.append((name, " ".join(parts[2].split()) if len(parts) == 3 else "", ok))
    return rows


def _meter(img: Image.Image, box, probe, white: bool) -> None:
    x1, y1, x2, _ = box
    t.panel(img, box, t.RADIUS_LG, LIGHT_SURFACE if white else t.SURFACE, None if white else t.BORDER,
            shadow=not white)
    ink, muted = (INK_LIGHT, MUTED_LIGHT) if white else (t.TEXT, t.MUTED)
    t.text(img, (x1 + 28, y1 + 36), "Muscle level", t.SIZE_MD, "semibold", ink, anchor="lm")
    if probe.relaxed is None or not probe.threshold:
        t.text(img, (x1 + 28, y1 + 80), "Keep your jaw relaxed: measuring your resting level…", t.SIZE_SM,
               "regular", muted, anchor="lm")
        return
    t.text(img, (x2 - 28, y1 + 36), f"{probe.level / probe.relaxed:.1f}× rest  ·  threshold {probe.ratio:.1f}×",
           t.SIZE_SM, "medium", muted, anchor="rm")
    bar_x1, bar_x2 = x1 + 80, x2 - 28
    rows = [("All", probe.level)] + [(f"Ch {i + 1}", v) for i, v in enumerate(probe.channel_levels)]
    for k, (label, value) in enumerate(rows[:3]):
        cy = y1 + 84 + k * 34
        frac = min(1.0, value / (2 * probe.threshold))   # full bar = 2x the threshold: the tick sits mid-way
        t.text(img, (x1 + 28, cy), label, t.SIZE_XS, "semibold", muted, anchor="lm")
        t.progress(img, (bar_x1, cy - 6, bar_x2, cy + 6), frac,
                   t.SUCCESS if value > probe.threshold else t.PRIMARY, (220, 225, 232) if white else t.SURFACE_2)
    tick_x = (bar_x1 + bar_x2) / 2
    t.rounded(img, (tick_x - 1.5, y1 + 68, tick_x + 1.5, y1 + 84 + 2 * 34 + 14), 2, ink)


def render(probe, lines: list[tuple[str, bool]], now: float, w: int, h: int, synthetic: bool = False) -> Image.Image:
    white = now < probe.white_until
    img = Image.new("RGB", (w, h), t.WHITE) if white else t.canvas(w, h)
    ink, muted, card = (INK_LIGHT, MUTED_LIGHT, LIGHT_SURFACE) if white else (t.TEXT, t.MUTED, t.SURFACE)
    t.brand(img, (48, 52), t.SIZE_MD, ink)
    t.text(img, (w - 48, 52), "HEADSET TEST", t.SIZE_XS, "semibold", muted, anchor="rm")

    # Status disc: what the rider should do now, or the confirmation flash.
    cx, cy = w * 0.27, h * 0.44
    if white:
        t.circle(img, (cx, cy), 120, t.SUCCESS)
        t.icon(img, "check", (cx, cy), 120, t.WHITE, 2.4)
        title, sub = "Clench detected", f"Clench #{probe.clenches}"
    else:
        t.circle(img, (cx, cy), 120 + 6 * t.pulse(now), t.mix(t.BG, t.PRIMARY, 0.07))
        t.ring(img, (cx, cy), 104, 1.0, 3, t.SURFACE_2, None)
        t.icon(img, "jaw", (cx, cy), 96, t.PRIMARY, 2.0)
        title = "Clench your jaw" if probe.relaxed is not None else "Stay relaxed"
        sub = f"{probe.clenches} clench{'' if probe.clenches == 1 else 'es'} detected so far"
    t.text(img, (cx, cy + 172), title, t.SIZE_2XL, "bold", ink, anchor="mm")
    t.text(img, (cx, cy + 216), sub, t.SIZE_MD, "regular", muted, anchor="mm")

    # Stage checklist: the first amber row is where the chain breaks.
    px1, py1, px2 = w * 0.52, 110, w - 48
    rows = _rows(lines)
    list_bottom = py1 + 70 + 56 * len(rows)
    t.panel(img, (px1, py1, px2, list_bottom), t.RADIUS_LG, card, None if white else t.BORDER, shadow=not white)
    t.text(img, (px1 + 28, py1 + 38), "Signal chain", t.SIZE_MD, "semibold", ink, anchor="lm")
    for k, (name, detail, ok) in enumerate(rows):
        ry = py1 + 92 + 56 * k
        color = t.SUCCESS if ok else t.WARNING
        t.circle(img, (px1 + 42, ry), 14, t.mix(card, color, 0.22))
        t.icon(img, "check" if ok else "alert", (px1 + 42, ry), 16, color, 2.2)
        t.text(img, (px1 + 68, ry - 9), name, t.SIZE_SM, "semibold", ink, anchor="lm")
        t.text(img, (px1 + 68, ry + 12), detail, t.SIZE_XS, "regular", muted, anchor="lm",
               max_w=int(px2 - px1 - 92))
    _meter(img, (px1, list_bottom + 20, px2, list_bottom + 20 + 196), probe, white)
    if not white:
        hints = [("UP / DOWN", "Threshold"), ("R", "Re-measure rest")]
        hints += [("SPACE", "Fake clench")] if synthetic else []
        t.key_hints(img, w - 48, h - 36, hints + [("ESC", "Quit")])
    return img
