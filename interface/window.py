"""Full-screen OpenCV windows that really fill the screen on macOS.

Why: OpenCV's Cocoa backend does switch the window to full screen, but it draws the picture at its own pixel size
instead of stretching it. A 1280 x 800 canvas on this MacBook Air (1470 x 956 points) therefore covered only 73% of
the screen ("the eye-tracking window takes 3/4 of the screen"). Fix: scale every frame to the screen size just
before showing it. Gaze is measured as a fraction of the screen and every canvas is drawn edge to edge, so the
fractions (and all the selection logic built on them) are unchanged.
"""

from __future__ import annotations

import functools
import logging
import subprocess

log = logging.getLogger("interface.window")

FALLBACK_SIZE = (1280, 800)  # if the screen size cannot be read: show frames unscaled, as before


@functools.lru_cache(maxsize=1)
def screen_size() -> tuple[int, int]:
    """Main display size in points (what OpenCV windows use), e.g. (1470, 956). Read once and cached."""
    try:
        # AppKit's main screen frame, through JavaScript for Automation: no extra library, no permission prompt
        # (asking Finder would make macOS ask "allow Xavier to control Finder?"). ~0.1 s, once.
        script = 'ObjC.import("AppKit"); var f = $.NSScreen.mainScreen.frame; f.size.width + "," + f.size.height'
        out = subprocess.run(["osascript", "-l", "JavaScript", "-e", script],
                             capture_output=True, text=True, timeout=3).stdout
        width, height = (int(float(v)) for v in out.strip().split(","))
        if width >= 640 and height >= 480:
            return width, height
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        log.warning("could not read the screen size (%s): showing frames unscaled", error)
    return FALLBACK_SIZE


def open_fullscreen(cv2, name: str) -> None:
    """Create `name` as a full-screen window (call once, before the first show())."""
    cv2.namedWindow(name, cv2.WINDOW_NORMAL)
    cv2.setWindowProperty(name, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)


def fit_to_screen(cv2, image):
    """The frame stretched to exactly the screen size (no-op if it already is)."""
    width, height = screen_size()
    if image.shape[1] == width and image.shape[0] == height:
        return image
    # INTER_AREA when shrinking (sharp text), INTER_LINEAR when enlarging (smooth, fast).
    shrinking = image.shape[1] > width
    return cv2.resize(image, (width, height), interpolation=cv2.INTER_AREA if shrinking else cv2.INTER_LINEAR)


def show(cv2, name: str, image) -> None:
    """cv2.imshow, but filling the whole screen."""
    cv2.imshow(name, fit_to_screen(cv2, image))
