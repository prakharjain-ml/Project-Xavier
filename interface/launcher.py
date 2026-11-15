"""Xavier launcher: the app's home screen. Pick a mode with the mouse or the keyboard; it runs exactly what a human
would type (`./demo.sh <mode>`, or the headset test) and comes back here when that ends, with a short note on how
it ended (the last error line, if any). Every run's output is kept in data/raw/sessions/.

    python -m interface.launcher        (or open Xavier.app, built by tools/build_app.sh)

Live chair modes ask for an explicit confirmation first. The launcher itself never opens a port or a camera.
"""

from __future__ import annotations

import logging
import math
import re
import subprocess
import threading
import time
from dataclasses import replace
from pathlib import Path

from interface import window
from interface.launcher_modes import Mode, readiness
from interface.launcher_view import H, W, HomeState, all_modes, card_rects, render_home, render_starting, sheet_buttons

log = logging.getLogger("interface.launcher")

WINDOW = "Xavier"
REPO_ROOT = Path(__file__).resolve().parents[1]
LOG_DIR = REPO_ROOT / "data" / "raw" / "sessions"
READINESS_EVERY_S = 3.0      # re-check what is plugged in this often (in the background)
HOVER_RATE = 14.0            # hover glow approaches its target at this rate per second (about 150 ms to settle)
FRAME_MS = 15                # wait per pass for a key: ~40-60 redraws a second keeps the motion smooth
STARTING_S = 0.7             # "Starting ..." screen before handing the screen to the mode
TOAST_S = 9.0
ESC, ENTER, RETURN, SPACE, TAB = 27, 13, 10, 32, 9
UP, DOWN, LEFT, RIGHT = 63232, 63233, 63234, 63235   # cv2.waitKeyEx arrow codes on macOS (Cocoa)
ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
LOG_PREFIX = re.compile(r"^\d{4}-\d\d-\d\d [\d:,.]+ (INFO|WARNING|ERROR|CRITICAL) [\w.]+: ")
ERROR_WORDS = re.compile(r"error|failed|cannot|not found|refusing|gave up|no esp32|not on the", re.I)


class ReadinessWatcher:
    """Runs the read-only readiness checks on a background thread so the screen never stutters."""

    def __init__(self) -> None:
        self.value: dict[str, bool] = {}
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="readiness", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.value = readiness()
            except Exception:  # a check failing must not take the launcher down; show "not detected" instead
                log.exception("readiness check failed")
                self.value = {}
            self._stop.wait(READINESS_EVERY_S)


class Pointer:
    """Mouse position and clicks, converted from screen pixels back to the 1280 x 800 canvas."""

    def __init__(self) -> None:
        self.pos: tuple[float, float] | None = None
        self.clicks: list[tuple[float, float]] = []
        self.down = False

    def on_event(self, event: int, x: int, y: int, flags: int, param) -> None:
        import cv2

        sw, sh = window.screen_size()
        point = (x * W / sw, y * H / sh)
        self.pos = point
        if event == cv2.EVENT_LBUTTONDOWN:
            self.down = True
        elif event == cv2.EVENT_LBUTTONUP:
            self.down = False
            self.clicks.append(point)


def _inside(point: tuple[float, float] | None, rect) -> bool:
    return point is not None and rect[0] <= point[0] < rect[2] and rect[1] <= point[1] < rect[3]


def card_at(point: tuple[float, float] | None) -> int | None:
    return next((i for i, rect in enumerate(card_rects()) if _inside(point, rect)), None)


def neighbour(index: int, key: int) -> int:
    """Keyboard focus: the nearest card in the arrow's direction (rows are uneven, so go by geometry)."""
    rects = card_rects()
    cx, cy = (rects[index][0] + rects[index][2]) / 2, (rects[index][1] + rects[index][3]) / 2
    best, best_cost = index, float("inf")
    for i, (x1, y1, x2, y2) in enumerate(rects):
        dx, dy = (x1 + x2) / 2 - cx, (y1 + y2) / 2 - cy
        forward = {LEFT: -dx, RIGHT: dx, UP: -dy, DOWN: dy}[key]
        across = abs(dy) if key in (LEFT, RIGHT) else abs(dx)
        if i != index and forward > 1 and forward + 3 * across < best_cost:
            best, best_cost = i, forward + 3 * across
    return best


def summary_line(log_text: str) -> str | None:
    """The most useful line of a finished run: the last error-looking line, else the last line."""
    lines = [LOG_PREFIX.sub("", ANSI.sub("", line)).strip() for line in log_text.splitlines()]
    lines = [line for line in lines if line and not line.startswith(("Finished.", "objc[", "pygame ", "Hello from"))
             and "board_logger" not in line and not line.startswith(("{", "}", '"'))]
    errors = [line for line in lines if ERROR_WORDS.search(line)]
    chosen = (errors or lines or [None])[-1]
    return None if chosen is None else chosen[:220]


def run_mode(cv2, mode: Mode) -> tuple[str, str]:
    """Hand the screen to `mode` and wait for it to end. Returns the toast (text, tone) to show afterwards."""
    started = time.monotonic()
    while (now := time.monotonic()) - started < STARTING_S:
        window.show(cv2, WINDOW, render_starting(mode, now))
        cv2.waitKey(16)
    cv2.destroyWindow(WINDOW)
    cv2.waitKey(1)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOG_DIR / f"launcher_{time.strftime('%Y-%m-%d_%H-%M-%S')}_{mode.key}.log"
    log.info("starting %s: %s (output in %s)", mode.key, " ".join(mode.command()), log_path)
    try:
        with open(log_path, "w") as out:
            code = subprocess.run(mode.command(), cwd=REPO_ROOT, stdout=out, stderr=subprocess.STDOUT).returncode
    except OSError as error:
        log.exception("could not start %s", mode.key)
        return f"{mode.title} could not start: {error}", "warn"
    line = summary_line(log_path.read_text(errors="replace"))
    log.info("%s ended with code %s: %s", mode.key, code, line)
    if code == 0:
        return f"{mode.title} finished. Log saved to {log_path.name}.", "success"
    return f"{mode.title} stopped: {line or f'exit code {code}'}", "warn"


def _open(cv2, pointer: Pointer) -> None:
    window.open_fullscreen(cv2, WINDOW)
    cv2.setMouseCallback(WINDOW, pointer.on_event)


def ease_hover(hover: dict[int, float], hovered: int | None, dt: float) -> dict[int, float]:
    """Move each card's hover glow toward 1 (hovered) or 0, frame-rate independently (exponential approach)."""
    step = 1 - math.exp(-HOVER_RATE * dt)
    out = {}
    for i in range(len(all_modes())):
        current = hover.get(i, 0.0)
        value = current + ((1.0 if i == hovered else 0.0) - current) * step
        if value > 0.01:
            out[i] = value
    return out


def handle_sheet(state: HomeState, key: int, clicks: list) -> tuple[HomeState, Mode | None]:
    """Live-chair confirmation. Returns (new state, mode to start or None)."""
    cancel, start = sheet_buttons()
    for point in clicks:
        if _inside(point, start):
            return replace(state, sheet=None), state.sheet
        if _inside(point, cancel):
            return replace(state, sheet=None), None
    if key == ESC:
        return replace(state, sheet=None), None
    if key in (LEFT, RIGHT, TAB):
        return replace(state, sheet_focus=1 - state.sheet_focus), None
    if key in (ENTER, RETURN, SPACE):
        return replace(state, sheet=None), state.sheet if state.sheet_focus == 1 else None
    return state, None


def choose(state: HomeState, index: int, now: float) -> tuple[HomeState, Mode | None]:
    mode = all_modes()[index]
    if mode.live:  # the wheels can move: ask first, with Cancel focused
        return replace(state, focus=index, sheet=mode, sheet_focus=0, sheet_open_s=now), None
    return replace(state, focus=index), mode


def handle_home(state: HomeState, key: int, clicks: list, now: float) -> tuple[HomeState, Mode | None, bool]:
    """Home screen input. Returns (new state, mode to start or None, quit?)."""
    if key == ESC:
        return state, None, True
    chosen = None
    if key in (UP, DOWN, LEFT, RIGHT):
        state = replace(state, focus=neighbour(state.focus, key))
    elif key == TAB:
        state = replace(state, focus=(state.focus + 1) % len(all_modes()))
    elif key in (ENTER, RETURN, SPACE):
        state, chosen = choose(state, state.focus, now)
    for point in clicks:
        index = card_at(point)
        if index is not None:
            state, chosen = choose(state, index, now)
    return state, chosen, False


def main() -> int:
    import cv2

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s",
                        handlers=[logging.StreamHandler(), logging.FileHandler(LOG_DIR / "launcher.log")])
    watcher, pointer = ReadinessWatcher(), Pointer()
    watcher.start()
    _open(cv2, pointer)
    now = last = time.monotonic()
    state = HomeState(started_s=now, clock=now)
    try:
        while True:
            now = time.monotonic()
            hovered = card_at(pointer.pos) if state.sheet is None else None
            if state.toast is not None and now - state.toast_since > TOAST_S:
                state = replace(state, toast=None)
            state = replace(state, clock=now, readiness=dict(watcher.value),
                            hover=ease_hover(state.hover, hovered, now - last),
                            pressed=hovered if pointer.down else None)
            last = now
            window.show(cv2, WINDOW, render_home(state))
            key = cv2.waitKeyEx(FRAME_MS)
            clicks, pointer.clicks = pointer.clicks, []
            if state.sheet is not None:
                state, chosen = handle_sheet(state, key, clicks)
            else:
                state, chosen, quit_now = handle_home(state, key, clicks, now)
                if quit_now:
                    break
            if chosen is not None:
                text, tone = run_mode(cv2, chosen)
                _open(cv2, pointer)
                now = last = time.monotonic()
                state = replace(state, toast=(text, tone), toast_since=now, started_s=now, hover={})
    finally:
        watcher.stop()
        cv2.destroyAllWindows()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
