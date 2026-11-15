"""Launcher drawing (pure): home screen of mode cards, readiness chips, the live-chair confirmation sheet, toasts.
Layout helpers (card_rects, sheet_buttons) are shared with the input code so clicks hit what is drawn."""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
from PIL import Image

from interface import theme as t
from interface.launcher_modes import CHAIR, HEADSET, LIVE, PRACTICE, ROOM_CAMERA, Mode

W, H = 1280, 800
MARGIN, GAP, COLS = 48, 16, 4
CARD_H = 122
CARD_W = (W - 2 * MARGIN - GAP * (COLS - 1)) // COLS
PRACTICE_Y, LIVE_Y = 236, 552
ENTER_STAGGER_S, ENTER_S = 0.04, 0.40   # cards rise in one after another (40 ms apart, 400 ms each)
SHEET_W, SHEET_H = 640, 372
FOOTER_Y = H - 30
TOAST_BOTTOM = H - 58  # between the last card row (ends at 674) and the footer
CHECKLIST = ("Wheels are off the ground, or the path is clear",
             "Someone holds the kill switch",
             "The rider is seated and calibrated")


@dataclass
class HomeState:
    readiness: dict[str, bool] = field(default_factory=dict)
    hover: dict[int, float] = field(default_factory=dict)   # card index -> 0..1 eased hover amount
    focus: int = 0                                          # keyboard focus (card index)
    pressed: int | None = None                              # card being clicked (press feedback)
    sheet: Mode | None = None                               # live mode waiting for confirmation
    sheet_focus: int = 0                                    # 0 = Cancel, 1 = Start
    sheet_open_s: float = 0.0
    toast: tuple[str, str] | None = None                    # (text, tone: info|success|warn)
    toast_since: float = 0.0
    started_s: float = 0.0                                  # launcher start time, for the entrance animation
    clock: float = 0.0


def all_modes() -> tuple[Mode, ...]:
    return PRACTICE + LIVE


def card_rects() -> list[tuple[float, float, float, float]]:
    rects = []
    for i, _ in enumerate(PRACTICE):
        row, col = divmod(i, COLS)
        x, y = MARGIN + col * (CARD_W + GAP), PRACTICE_Y + row * (CARD_H + GAP)
        rects.append((x, y, x + CARD_W, y + CARD_H))
    for i, _ in enumerate(LIVE):
        x = MARGIN + i * (CARD_W + GAP)
        rects.append((x, LIVE_Y, x + CARD_W, LIVE_Y + CARD_H))
    return rects


def sheet_rect() -> tuple[float, float, float, float]:
    x1, y1 = (W - SHEET_W) / 2, (H - SHEET_H) / 2
    return x1, y1, x1 + SHEET_W, y1 + SHEET_H


def sheet_buttons() -> tuple[tuple[float, float, float, float], tuple[float, float, float, float]]:
    """(cancel, start) button rectangles."""
    x1, _, x2, y2 = sheet_rect()
    by1, by2 = y2 - 32 - 52, y2 - 32
    mid = (x1 + x2) / 2
    return (x1 + 32, by1, mid - 8, by2), (mid + 8, by1, x2 - 32, by2)


def _section(img, y: float, label: str, dot) -> None:
    t.circle(img, (MARGIN + 4, y), 4, dot)
    t.text(img, (MARGIN + 16, y), label, t.SIZE_XS, "semibold", t.MUTED, anchor="lm")
    lw = t.text_size(label, t.SIZE_XS, "semibold")[0]
    t.rounded(img, (MARGIN + 28 + lw, y, W - MARGIN, y + 1), 0, t.BORDER)


def _missing(mode: Mode, readiness: dict[str, bool]) -> list[str]:
    return [n for n in mode.needs if not readiness.get(n, False)]


def _card(img, mode: Mode, rect, hover: float, focused: bool, pressed: bool, missing: list[str],
          enter: float) -> None:
    accent = t.WARNING if mode.live else t.PRIMARY
    lift = 3 * hover - (2 if pressed else 0)   # hover lifts the card, a press pushes it back down
    rise = 14 * (1 - t.ease_out(enter))        # entrance: slide up into place
    x1, y1, x2, y2 = rect
    y1, y2 = y1 - lift + rise, y2 - lift + rise
    fade = t.ease_out(enter)

    def c(color):  # entrance fade: colours start at the background and settle to their own
        return t.mix(t.BG, color, fade)

    fill = t.mix(t.SURFACE, t.SURFACE_2, hover * 0.8)
    border = t.mix(t.BORDER, accent, max(0.55 * hover, 1.0 if focused else 0.0))
    t.panel(img, (x1, y1, x2, y2), t.RADIUS_MD, c(fill), c(border), shadow=hover > 0.05 and fade > 0.9)
    if focused:  # a visible focus ring for keyboard users (2 px, outside the border)
        t.rounded(img, (x1 - 3, y1 - 3, x2 + 3, y2 + 3), t.RADIUS_MD + 3, None, c(accent), 2)
    t.circle(img, (x1 + 38, y1 + 40), 22, c(t.mix(fill, accent, 0.16 + 0.10 * hover)))
    t.icon(img, mode.icon, (x1 + 38, y1 + 40), 24, c(accent), 2.0)
    title_room = CARD_W - 86 - (64 if mode.live else 0)
    t.text(img, (x1 + 72, y1 + 40), mode.title, t.SIZE_MD, "semibold", c(t.TEXT), anchor="lm", max_w=title_room)
    t.text(img, (x1 + 20, y1 + 80), mode.blurb, t.SIZE_SM, "regular", c(t.MUTED), anchor="lm", max_w=CARD_W - 36)
    status, color = ("Ready", t.SUCCESS) if not missing else ("Needs " + " + ".join(missing), t.WARNING)
    t.circle(img, (x1 + 24, y1 + 104), 3.5, c(color))
    t.text(img, (x1 + 34, y1 + 104), status, t.SIZE_XS, "medium", c(color), anchor="lm", max_w=CARD_W - 50)
    if mode.live:
        t.pill(img, x2 - 16 - t.pill_width("LIVE", t.SIZE_XS, "bold", height=22), y1 + 40, "LIVE", c(t.BG),
               c(t.WARNING), t.SIZE_XS, "bold", height=22)


def _readiness_chips(img, readiness: dict[str, bool]) -> None:
    x = W - MARGIN
    for name, icon in reversed(((HEADSET, "wifi"), (ROOM_CAMERA, "camera"), (CHAIR, "motor"))):
        ok = readiness.get(name, False)
        label = name.capitalize()
        w = t.text_size(label, t.SIZE_SM, "medium")[0] + 64
        t.rounded(img, (x - w, 34, x, 70), 18, t.SURFACE, t.BORDER)
        t.icon(img, icon, (x - w + 22, 52), 16, t.SUCCESS if ok else t.FAINT, 2.0)
        t.text(img, (x - w + 38, 52), label, t.SIZE_SM, "medium", t.TEXT if ok else t.MUTED, anchor="lm")
        t.circle(img, (x - 16, 52), 3.5, t.SUCCESS if ok else t.WARNING)
        x -= w + 10


def _sheet(img: Image.Image, mode: Mode, focus: int, open_t: float) -> Image.Image:
    # Dim everything behind the sheet so it reads as a separate, blocking question.
    img = Image.blend(img, Image.new("RGB", img.size, t.BG), 0.72 * t.ease_out(open_t))
    x1, y1, x2, y2 = sheet_rect()
    rise = 18 * (1 - t.ease_out(open_t))
    y1, y2 = y1 + rise, y2 + rise
    t.panel(img, (x1, y1, x2, y2), t.RADIUS_LG)
    t.circle(img, (x1 + 56, y1 + 60), 26, t.mix(t.SURFACE, t.WARNING, 0.18))
    t.icon(img, "alert", (x1 + 56, y1 + 58), 26, t.WARNING, 2.0)
    t.text(img, (x1 + 98, y1 + 48), f"Start {mode.title}?", t.SIZE_XL, "bold", t.TEXT, anchor="lm")
    t.text(img, (x1 + 98, y1 + 80), "The real wheels will move.", t.SIZE_MD, "regular", t.MUTED, anchor="lm")
    for i, item in enumerate(CHECKLIST):
        cy = y1 + 140 + i * 50
        t.rounded(img, (x1 + 32, cy - 20, x2 - 32, cy + 20), 12, t.SURFACE_2)
        t.icon(img, "check", (x1 + 56, cy), 18, t.SUCCESS, 2.2)
        t.text(img, (x1 + 78, cy), item, t.SIZE_SM, "medium", t.TEXT, anchor="lm")
    cancel, start = ((b[0], b[1] + rise, b[2], b[3] + rise) for b in sheet_buttons())
    t.rounded(img, cancel, 14, t.SURFACE_2, t.PRIMARY if focus == 0 else t.BORDER, 2 if focus == 0 else 1)
    t.text(img, ((cancel[0] + cancel[2]) / 2, (cancel[1] + cancel[3]) / 2), "Cancel", t.SIZE_MD, "semibold",
           t.TEXT, anchor="mm")
    t.rounded(img, start, 14, t.WARNING, t.TEXT if focus == 1 else None, 2)
    t.text(img, ((start[0] + start[2]) / 2, (start[1] + start[3]) / 2), "Start live chair", t.SIZE_MD, "bold",
           t.BG, anchor="mm")
    return img


def _toast(img, text: str, tone: str, age: float) -> None:
    color = {"success": t.SUCCESS, "warn": t.WARNING}.get(tone, t.PRIMARY)
    icon = {"success": "check", "warn": "alert"}.get(tone, "pulse")
    show = t.ease_out(age / t.DUR_STATE)
    lines = t.wrap(text, t.SIZE_SM, "medium", 760)[:2]
    h = 30 + 24 * len(lines)
    w = min(880, max(t.text_size(line, t.SIZE_SM, "medium")[0] for line in lines) + 96)
    x1, y2 = (W - w) / 2, TOAST_BOTTOM + 16 * (1 - show)
    t.panel(img, (x1, y2 - h, x1 + w, y2), t.RADIUS_MD, t.SURFACE, t.mix(t.BORDER, color, 0.6))
    t.icon(img, icon, (x1 + 32, y2 - h / 2), 20, color, 2.2)
    for i, line in enumerate(lines):
        t.text(img, (x1 + 58, y2 - h + 27 + 24 * i), line, t.SIZE_SM, "medium", t.TEXT, anchor="lm")


def render_home(state: HomeState) -> np.ndarray:
    img = t.canvas(W, H)
    t.brand(img, (MARGIN, 52), t.SIZE_LG)
    _readiness_chips(img, state.readiness)
    t.text(img, (MARGIN, 128), "Choose how to drive", t.SIZE_2XL, "bold", t.TEXT, anchor="lm")
    t.text(img, (MARGIN, 172), "Practice modes never move the wheels. Live modes ask before they start.",
           t.SIZE_MD, "regular", t.MUTED, anchor="lm")
    _section(img, 214, "PRACTICE  ·  NOTHING MOVES", t.PRIMARY)
    _section(img, 530, "LIVE CHAIR  ·  THE WHEELS MOVE", t.WARNING)
    since = state.clock - state.started_s
    for i, (mode, rect) in enumerate(zip(all_modes(), card_rects())):
        enter = (since - i * ENTER_STAGGER_S) / ENTER_S
        _card(img, mode, rect, state.hover.get(i, 0.0), i == state.focus and state.sheet is None,
              state.pressed == i, _missing(mode, state.readiness), enter)
    t.key_hints(img, W - MARGIN, FOOTER_Y, (("ARROWS", "Move"), ("ENTER", "Start"), ("ESC", "Quit")))
    t.text(img, (MARGIN, FOOTER_Y), "Session logs: data/raw/sessions", t.SIZE_XS, "medium", t.FAINT, anchor="lm")
    if state.toast is not None and state.sheet is None:
        _toast(img, state.toast[0], state.toast[1], state.clock - state.toast_since)
    if state.sheet is not None:
        img = _sheet(img, state.sheet, state.sheet_focus, (state.clock - state.sheet_open_s) / t.DUR_ENTER)
    return t.to_bgr(img)


def render_starting(mode: Mode, clock: float) -> np.ndarray:
    """Shown while the chosen mode starts (cameras and models take a few seconds to open)."""
    img = t.canvas(W, H)
    t.brand(img, (MARGIN, 52), t.SIZE_LG)
    cx, cy = W / 2, H / 2 - 30
    t.ring(img, (cx, cy), 46, 1.0, 5, t.SURFACE_2, None)
    head = (clock * 1.1) % 1.0
    for k in range(12):  # a short comet that travels round the ring: "working", without a fake percentage
        a = 2 * math.pi * (head - k * 0.014)
        t.circle(img, (cx + 46 * math.sin(a), cy - 46 * math.cos(a)), 3.0 - k * 0.18,
                 t.mix(t.SURFACE_2, t.PRIMARY, 1 - k / 12))
    t.icon(img, mode.icon, (cx, cy), 30, t.PRIMARY, 2.0)
    t.text(img, (cx, cy + 100), f"Starting {mode.title}", t.SIZE_XL, "bold", t.TEXT, anchor="mm")
    t.text(img, (cx, cy + 140), "Opening cameras and models. This takes a few seconds.", t.SIZE_MD, "regular",
           t.MUTED, anchor="mm")
    return t.to_bgr(img)
