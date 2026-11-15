"""Full-screen layouts shared by every part of the app, drawn with interface.theme. Pure: they return a BGR
image and never open a window, so they are testable and screenshot-able offline.

- instruction(): one centred card (jaw calibration steps, errors, waits).
- face_check(): "sit still, we can see your face", with an optional countdown ring.
- calibration_target(): one calibration dot: pulse while the eyes travel, capture ring while sampling.
- region_check(): the validation box with the live gaze dot.
"""

from __future__ import annotations

import re

import numpy as np

from interface import theme as t

CARD_W = 760


def _header(img, w: int, subtitle: str) -> None:
    t.brand(img, (48, 52), t.SIZE_MD)
    t.text(img, (w - 48, 52), subtitle.upper(), t.SIZE_XS, "semibold", t.MUTED, anchor="rm")


def instruction(w: int, h: int, title: str, body: str = "", icon: str = "pulse", tone: str = "info",
                step: int | None = None, total: int | None = None, footer: str = "",
                hints: tuple[tuple[str, str], ...] = (), clock: float = 0.0, section: str = "Setup") -> np.ndarray:
    """A centred card: icon badge, big title, one-paragraph body, optional step dots and key hints.
    tone: info (cyan), success (green), warn (amber)."""
    img = t.canvas(w, h)
    _header(img, w, section)
    accent = {"success": t.SUCCESS, "warn": t.WARNING}.get(tone, t.PRIMARY)
    body_lines = t.wrap(body, t.SIZE_LG, "regular", CARD_W - 120) if body else []
    card_h = 262 + 40 * len(body_lines) + (46 if step is not None else 0)  # content height + 40 px padding
    x1, y1 = (w - CARD_W) / 2, (h - card_h) / 2 + 20
    t.panel(img, (x1, y1, x1 + CARD_W, y1 + card_h))
    cx, y = w / 2, y1 + 92
    halo = 52 + 6 * t.pulse(clock)  # slow breathing halo: "the system is listening"
    t.circle(img, (cx, y), halo, t.mix(t.SURFACE, accent, 0.18))
    t.circle(img, (cx, y), 44, t.mix(t.SURFACE, accent, 0.30))
    t.icon(img, icon, (cx, y), 40, accent, 2.2)
    y += 92
    t.text(img, (cx, y), title, t.SIZE_2XL, "bold", t.TEXT, anchor="mm", max_w=CARD_W - 80)
    y += 56
    for line in body_lines:
        t.text(img, (cx, y), line, t.SIZE_LG, "regular", t.MUTED, anchor="mm")
        y += 40
    if step is not None and total:
        t.steps(img, (cx, y + 18), total, step)
    if footer:
        t.text(img, (cx, h - 48), footer, t.SIZE_SM, "medium", t.FAINT, anchor="mm")
    if hints:
        t.key_hints(img, w - 48, h - 48, hints)
    return t.to_bgr(img)


def jaw_instruction(w: int, h: int, message: str, clock: float = 0.0) -> np.ndarray:
    """Turn the jaw calibration's plain prompts (bci.jaw_live.JawConfirmSource.calibrate) into cards.
    Presentation only: the prompt text and its timing come from the calibration, unchanged."""
    lower = message.lower()
    seconds = re.search(r"\((\d+)\s*s\)", message)
    count = re.search(r"\((\d+)/(\d+)\)", message)
    if "failed" in lower:
        return instruction(w, h, "Jaw calibration failed", "Check that the electrodes and ear clip touch skin, "
                           "then start again.", "alert", "warn", section="Headset setup")
    if "clench" in lower and count:
        i, n = int(count.group(1)), int(count.group(2))
        return instruction(w, h, "Clench your jaw", f"Bite down firmly and hold. Clench {i} of {n}.", "jaw",
                           step=i, total=n + 1, section="Headset setup", clock=clock)
    if "relax your jaw" in lower:
        body = "Teeth apart, breathe normally, keep still"
        body += f" for {seconds.group(1)} seconds." if seconds else "."
        return instruction(w, h, "Relax your jaw", body, "pulse", step=0, total=4, section="Headset setup",
                           clock=clock)
    if lower.strip() == "relax":
        return instruction(w, h, "Relax", "Let go and rest for a moment.", "pulse", "success",
                           section="Headset setup", clock=clock)
    return instruction(w, h, message, "", "pulse", section="Headset setup", clock=clock)


def face_check(w: int, h: int, face_found: bool, countdown: float | None = None,
               title: str = "Eye calibration", hint: str = "Sit as you will in the chair and keep your head still.",
               hints: tuple[tuple[str, str], ...] = (("ESC", "Quit"),)) -> np.ndarray:
    """Before calibrating: is the face visible? countdown 0..1 fills a ring before the dots start."""
    img = t.canvas(w, h)
    _header(img, w, "Calibration")
    cx, cy = w / 2, h / 2 - 30
    if face_found:
        t.circle(img, (cx, cy), 92, t.mix(t.BG, t.SUCCESS, 0.10))
        t.ring(img, (cx, cy), 80, 1.0 if countdown is None else countdown, 6, t.SUCCESS, t.SURFACE_2)
        t.icon(img, "eye", (cx, cy), 56, t.SUCCESS, 2.0)
        status, color = "Face found", t.SUCCESS
    else:
        t.ring(img, (cx, cy), 80, 1.0, 3, t.SURFACE_2, None)
        t.icon(img, "eye", (cx, cy), 56, t.FAINT, 2.0)
        status, color = "Looking for your face. Move into the camera view.", t.WARNING
    t.text(img, (cx, cy + 140), title, t.SIZE_2XL, "bold", t.TEXT, anchor="mm")
    t.text(img, (cx, cy + 190), hint, t.SIZE_LG, "regular", t.MUTED, anchor="mm", max_w=w - 200)
    t.pill(img, cx - t.pill_width(status, t.SIZE_SM, dot=True) / 2, cy + 248, status, color, t.SURFACE_2,
           dot=color)
    if hints:
        t.key_hints(img, w - 48, h - 48, hints)
    return t.to_bgr(img)


def calibration_target(w: int, h: int, point: tuple[float, float], phase: str, progress: float,
                       index: int, total: int, radius: float = 18.0) -> np.ndarray:
    """One calibration dot at `point` (pixels). phase 'pulse' = the eyes travel to it (it breathes);
    'capture' = we are sampling (a ring fills). progress 0..1 within the phase."""
    img = t.canvas(w, h)
    x, y = point
    t.text(img, (w / 2, h - 56), f"Point {index + 1} of {total}", t.SIZE_SM, "semibold", t.MUTED, anchor="mm")
    done = (index + (progress if phase == "capture" else 0.0)) / max(1, total)
    t.progress(img, (w / 2 - 120, h - 34, w / 2 + 120, h - 28), done)
    t.circle(img, (x, y), radius * 2.6, t.mix(t.BG, t.PRIMARY, 0.10))
    if phase == "capture":
        t.ring(img, (x, y), radius * 2.0, progress, 4, t.WHITE, t.SURFACE_2)
    t.circle(img, (x, y), radius, t.PRIMARY)
    t.circle(img, (x, y), max(2.0, radius * 0.18), t.BG)  # the exact point to look at
    return t.to_bgr(img)


def region_check(w: int, h: int, box: tuple[float, float, float, float], gaze: tuple[float, float] | None,
                 on_target: bool, name: str) -> np.ndarray:
    """Validation: look at the highlighted region; the dot shows where we think you look."""
    img = t.canvas(w, h)
    _header(img, w, "Checking accuracy")
    t.rounded(img, box, t.RADIUS_LG, t.mix(t.BG, t.PRIMARY, 0.08), t.PRIMARY, 3)
    t.text(img, (w / 2, 110), f"Look at the {name} area", t.SIZE_XL, "bold", t.TEXT, anchor="mm")
    if gaze is not None:
        color = t.SUCCESS if on_target else t.WARNING
        t.circle(img, gaze, 16, t.mix(t.BG, color, 0.35))
        t.circle(img, gaze, 9, color)
    return t.to_bgr(img)
