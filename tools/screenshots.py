"""Render every screen of the app offline into data/raw/screenshots/after/ (no camera, headset or motors).

    python -m tools.screenshots

Uses a saved room picture (data/raw/screenshots/room_frame.jpg, else a plain grey frame) and fake states, so the
whole look can be reviewed and compared after any UI change. Also writes after_sheet.jpg (all screens, one image).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")  # pygame screens render off-screen

import cv2  # noqa: E402
import numpy as np  # noqa: E402

OUT = Path("data/raw/screenshots/after")
ROOM = Path("data/raw/screenshots/room_frame.jpg")
CANVAS = (1280, 800)
EYETRAX_SCREEN = (1470, 956)   # this MacBook Air's screen: EyeTrax draws at the real screen size


def save(name: str, image: np.ndarray) -> None:
    cv2.imwrite(str(OUT / f"{name}.png"), image)
    print("saved", name)


def launcher_screens() -> None:
    from interface import launcher_view as v
    from interface.launcher_modes import LIVE, PRACTICE

    ready = {"headset": True, "room camera": True, "chair controller": False}
    save("01_launcher_home", v.render_home(v.HomeState(readiness=ready, hover={1: 1.0}, focus=1, clock=9.0)))
    save("02_launcher_confirm_live", v.render_home(v.HomeState(readiness=ready, sheet=LIVE[0], sheet_focus=1,
                                                               clock=9.0, sheet_open_s=8.0)))
    save("03_launcher_after_error", v.render_home(v.HomeState(
        readiness={}, clock=9.0, toast_since=8.5, toast=("Look + jaw clench stopped: The laptop is not on the "
                                                         "headset's Wi-Fi, so the jaw clench cannot be read.", "warn"))))
    save("04_launcher_starting", v.render_starting(PRACTICE[1], 0.3))


def calibration_screens() -> None:
    from interface import screens

    w, h = EYETRAX_SCREEN
    save("05_eyetrax_face_check", screens.face_check(w, h, True, 0.55, "Eye calibration",
                                                     "Keep your head still. Follow the dot with your eyes."))
    save("06_eyetrax_no_face", screens.face_check(w, h, False, None, "Eye calibration",
                                                  "Keep your head still. Follow the dot with your eyes."))
    save("07_eyetrax_point", screens.calibration_target(w, h, (int(w * 0.9), int(h * 0.1)), "capture", 0.6, 3, 9,
                                                        22))
    save("08_gaze_check_region", screens.region_check(*CANVAS, (40, 40, 400, 360), (300, 220), True, "top-left"))


def jaw_screens() -> None:
    from interface import screens

    save("09_jaw_relax", screens.jaw_instruction(*CANVAS, "Relax your jaw, teeth apart (10 s)"))
    save("10_jaw_clench", screens.jaw_instruction(*CANVAS, "CLENCH your jaw now (2/3)"))
    save("11_jaw_failed", screens.jaw_instruction(*CANVAS, "Jaw calibration failed: check electrodes"))


def hud_screens() -> None:
    from vision import object_select as o
    from vision.detect_track import Track

    room = cv2.imread(str(ROOM)) if ROOM.exists() else np.full((720, 1280, 3), 90, np.uint8)
    tracks = [Track(1, "chair", 0.9, (380.0, 380.0, 640.0, 700.0), 1.8),
              Track(2, "couch", 0.8, (760.0, 300.0, 1180.0, 560.0), 3.2),
              Track(3, "potted plant", 0.7, (60.0, 230.0, 220.0, 420.0), 2.5)]
    boxes = o.hit_boxes(tracks, room.shape[1], room.shape[0])
    save("12_hud_choose", o.draw(cv2, room, tracks, boxes, o.Selection(), None, 10.0,
                                 "Look at an object to choose it", dwell_s=None, mode="Choose a destination"))
    save("13_hud_looking", o.draw(cv2, room, tracks, boxes, o.Selection(candidate=1, since=9.0), None, 10.0,
                                  "Looking at chair · clench to confirm", dwell_s=None, mode="Choose a destination"))
    save("14_hud_destination", o.draw(cv2, room, tracks, boxes, o.Selection(confirmed=2), None, 10.0,
                                      "Destination: couch · moving", dwell_s=None, mode="Drive to object"))


def pygame_screens() -> None:
    import pygame

    from interface import flicker
    from tools import jaw_flash as jf

    pygame.init()
    screen = pygame.display.set_mode(EYETRAX_SCREEN)

    def grab() -> np.ndarray:
        return cv2.cvtColor(np.transpose(pygame.surfarray.array3d(screen), (1, 0, 2)), cv2.COLOR_RGB2BGR)

    probe = jf.Probe(fs=1000.0, n=100)
    probe.total_samples, probe.rate, probe.relaxed, probe.level = 5000, 1000.0, 7.0, 25.0
    probe.channel_levels = (25.0, 6.0)
    lines = jf.stage_lines(probe, "connected (wifi, 1000 Hz, channels 1,2, rows [1, 2])", probe.last_data_at)
    jf.draw(screen, None, probe, lines, 0.0, True)
    save("15_headset_test", grab())
    probe.white_until, probe.clenches = 10.0, 3
    jf.draw(screen, None, probe, lines, 0.5, True)
    save("16_headset_clench_flash", grab())
    screen.blit(flicker.warning_surface(EYETRAX_SCREEN), (0, 0))
    save("17_ssvep_warning", grab())


def contact_sheet() -> None:
    files = sorted(OUT.glob("[0-9]*.png"))
    tiles = []
    for f in files:
        tile = cv2.resize(cv2.imread(str(f)), (640, 400), interpolation=cv2.INTER_AREA)
        cv2.putText(tile, f.stem, (12, 390), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (238, 211, 34), 1, cv2.LINE_AA)
        tiles.append(tile)
    while len(tiles) % 3:
        tiles.append(np.zeros_like(tiles[0]))
    sheet = np.vstack([np.hstack(tiles[i:i + 3]) for i in range(0, len(tiles), 3)])
    cv2.imwrite(str(OUT.parent / "after_sheet.jpg"), sheet, [cv2.IMWRITE_JPEG_QUALITY, 82])
    print("saved after_sheet.jpg with", len(files), "screens")


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    for step in (launcher_screens, calibration_screens, jaw_screens, hud_screens, pygame_screens):
        step()
    contact_sheet()
    return 0


if __name__ == "__main__":
    sys.exit(main())
