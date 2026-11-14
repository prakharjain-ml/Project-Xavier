"""Mode 1 flicker screen: four arrows, each flickering at its own exact rate, plus dwell feedback.

Run (from the repo root, on the demo laptop, by a human):
    python -m interface.flicker                 # fullscreen, 4 arrows; SPACE starts, ESC quits, F toggles stats
    python -m interface.flicker --single 12     # one big 12 Hz square, for the first real-signal check (2.10)
    python -m interface.flicker --fake-status   # animate dwell bars from a fake ControlStatus stream (2.8)
    python -m interface.flicker --seconds 60    # quit after 60 s and print the timing summary (gate: 0 dropped)

Rules this file follows (.cursor/rules/30-interface.mdc):
- Flicker is decided by counting display frames (interface/timing.py), never by sleep() or a clock.
- pygame owns the main thread (macOS), vsync on, fullscreen. cv2 is never imported here (SDL2 clash).
- Photosensitivity warning first; nothing flickers until SPACE.
- ControlStatus arrives through a latest-only queue (maxsize=1) read without blocking.
"""

from __future__ import annotations

import argparse
import logging
import queue
import sys
import threading
import time

import pygame

from interface.timing import (
    SLOW_FRAME_S,
    FrameStats,
    flicker_schedule,
    format_frame_summary,
    is_on,
    pacing_ok,
    update_frame_stats,
)
from shared.protocol import DISPLAY_HZ, ControlStatus, State, Target, frames_per_cycle

log = logging.getLogger("interface.flicker")

BLACK, WHITE, OUTLINE = (0, 0, 0), (255, 255, 255), (70, 70, 70)
DWELL_COLOR, MOVING_COLOR, ESTOP_COLOR = (255, 200, 0), (0, 220, 0), (230, 0, 0)
WINDOWED_SIZE = (1280, 800)
ARROW_FRACTION = 0.22  # arrow size as a fraction of the shorter screen side: large targets give stronger SSVEP
SINGLE_FRACTION = 0.6
WARNING_LINES = (
    "PHOTOSENSITIVITY WARNING",
    "This screen flickers at 6 to 15 times per second.",
    "Do not continue if you or anyone watching has epilepsy",
    "or has had a seizure triggered by flashing lights.",
    "",
    "Press SPACE to begin.  Press ESC to quit.",
)
KEYS = {"space": pygame.K_SPACE, "escape": pygame.K_ESCAPE}


def offer_latest(q: queue.Queue, item) -> None:
    """Put item into a maxsize=1 queue, replacing whatever is waiting. Never blocks the caller."""
    try:
        q.get_nowait()
    except queue.Empty:
        pass
    try:
        q.put_nowait(item)
    except queue.Full:  # another producer refilled it in between; dropping this one is fine
        pass


def read_latest(q: queue.Queue | None, current: ControlStatus) -> ControlStatus:
    if q is None:
        return current
    try:
        return q.get_nowait()
    except queue.Empty:
        return current


def open_display(windowed: bool) -> tuple[pygame.Surface, bool]:
    """Fullscreen with vsync. Returns (screen, has_vsync); without vsync, timing is only approximate."""
    flags = pygame.SCALED | (0 if windowed else pygame.FULLSCREEN)
    if windowed:
        size = WINDOWED_SIZE
    else:
        info = pygame.display.Info()
        size = (info.current_w, info.current_h)
    try:
        return pygame.display.set_mode(size, flags, vsync=1), True
    except pygame.error as error:
        log.warning("vsync unavailable (%s): frame timing will be approximate; do not use for the gate", error)
        return pygame.display.set_mode(size, flags), False


def show_warning(screen: pygame.Surface, clock: pygame.time.Clock, deadline: float | None) -> bool:
    """Photosensitivity screen. True when SPACE is pressed; False on ESC, window close or deadline."""
    font = pygame.font.Font(None, max(24, screen.get_height() // 22))
    while deadline is None or time.monotonic() < deadline:
        for event in pygame.event.get():
            if event.type == pygame.QUIT or (event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE):
                return False
            if event.type == pygame.KEYDOWN and event.key == pygame.K_SPACE:
                log.info("warning acknowledged: flicker starting")
                return True
        screen.fill(BLACK)
        for row, text in enumerate(WARNING_LINES):
            color = ESTOP_COLOR if row == 0 else WHITE
            surface = font.render(text, True, color)
            y = screen.get_height() // 3 + row * int(font.get_linesize() * 1.3)
            screen.blit(surface, surface.get_rect(center=(screen.get_width() // 2, y)))
        pygame.display.flip()
        clock.tick(30)  # static screen: no need to redraw at 60
    return False


def arrow_points(target: Target, center: tuple[int, int], size: int) -> list[tuple[int, int]]:
    """Triangle pointing in the target's direction."""
    x, y, h = center[0], center[1], size // 2
    return {
        Target.FWD: [(x, y - h), (x - h, y + h), (x + h, y + h)],
        Target.BACK: [(x, y + h), (x - h, y - h), (x + h, y - h)],
        Target.LEFT: [(x - h, y), (x + h, y - h), (x + h, y + h)],
        Target.RIGHT: [(x + h, y), (x - h, y - h), (x - h, y + h)],
    }[target]


def arrow_centers(width: int, height: int) -> dict[Target, tuple[int, int]]:
    return {
        Target.FWD: (width // 2, int(height * 0.2)),
        Target.BACK: (width // 2, int(height * 0.8)),
        Target.LEFT: (int(width * 0.18), height // 2),
        Target.RIGHT: (int(width * 0.82), height // 2),
    }


def draw_arrows(screen: pygame.Surface, frame_index: int, schedule: dict[Target, int], status: ControlStatus) -> None:
    width, height = screen.get_size()
    size = int(min(width, height) * ARROW_FRACTION)
    for target, center in arrow_centers(width, height).items():
        points = arrow_points(target, center, size)
        if is_on(frame_index, schedule[target]):
            pygame.draw.polygon(screen, WHITE, points)
        pygame.draw.polygon(screen, OUTLINE, points, width=3)  # static outline: rider can find dark arrows
        if target == status.held_target and status.state in (State.DWELLING, State.MOVING):
            color = MOVING_COLOR if status.state == State.MOVING else DWELL_COLOR
            bar = pygame.Rect(0, 0, size, max(8, size // 10))
            bar.midtop = (center[0], center[1] + size // 2 + 12)
            pygame.draw.rect(screen, OUTLINE, bar, width=2)
            pygame.draw.rect(screen, color, (bar.x, bar.y, int(bar.width * status.dwell_fraction), bar.height))


def draw_single(screen: pygame.Surface, frame_index: int, frames: int) -> None:
    width, height = screen.get_size()
    side = int(min(width, height) * SINGLE_FRACTION)
    square = pygame.Rect(0, 0, side, side)
    square.center = (width // 2, height // 2)
    pygame.draw.rect(screen, WHITE if is_on(frame_index, frames) else BLACK, square)
    pygame.draw.rect(screen, OUTLINE, square, width=3)


def draw_overlay(screen: pygame.Surface, font: pygame.font.Font, stats: FrameStats, status: ControlStatus) -> None:
    fps = stats.frames / stats.total_s if stats.total_s > 0 else 0.0
    text = f"{fps:5.1f} FPS  dropped {stats.dropped}  slow {stats.slow_frames}  {status.state.value}"
    screen.blit(font.render(text, True, OUTLINE), (10, 10))
    if status.state == State.E_STOP:
        banner = font.render("E-STOP  (operator re-arm required)", True, ESTOP_COLOR)
        screen.blit(banner, banner.get_rect(midtop=(screen.get_width() // 2, 10)))


def wait_until(deadline: float) -> float:
    """Busy-wait to `deadline`, return the next frame's deadline. If we are already late, re-anchor to now
    instead of rushing several frames to catch up (a burst of fast frames would distort the flicker)."""
    while time.monotonic() < deadline:
        pass
    now = time.monotonic()
    late = now - deadline > 1 / DISPLAY_HZ
    return (now if late else deadline) + 1 / DISPLAY_HZ


def run_flicker(screen: pygame.Surface, clock: pygame.time.Clock, single_frames: int | None, has_vsync: bool,
                deadline: float | None, status_queue: queue.Queue | None) -> FrameStats:
    """The 60 Hz loop. One iteration = one display refresh; frame_index drives every flicker."""
    schedule = flicker_schedule()
    font = pygame.font.Font(None, 28)
    stats, status = FrameStats(), ControlStatus(State.STOPPED, Target.NONE, 0.0)
    frame_index, show_stats, last_flip = 0, True, None
    next_frame_t = time.monotonic() + 1 / DISPLAY_HZ
    while True:
        for event in pygame.event.get():
            if event.type == pygame.QUIT or (event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE):
                return stats
            if event.type == pygame.KEYDOWN and event.key == pygame.K_f:
                show_stats = not show_stats
        status = read_latest(status_queue, status)
        screen.fill(BLACK)
        if single_frames is None:
            draw_arrows(screen, frame_index, schedule, status)
        else:
            draw_single(screen, frame_index, single_frames)
        if show_stats:
            draw_overlay(screen, font, stats, status)
        if not has_vsync:
            screen.blit(font.render("NO VSYNC: timing approximate", True, ESTOP_COLOR), (10, 40))
        pygame.display.flip()  # with working vsync this waits for the next refresh: that is our timebase
        if not has_vsync:
            # Fallback pacing only (no working vsync). pygame's tick() rounds to whole ms (16 ms -> 62.5 FPS,
            # 4% fast), so we wait for exact 1/60 s deadlines instead. The flicker phase still comes from
            # frame_index; this only spaces the frames evenly. Busy-waiting costs CPU, fine for a fallback.
            next_frame_t = wait_until(next_frame_t)
        now = time.monotonic()
        if last_flip is not None:  # the first frame's duration includes setup, so it is not counted
            frame_s = now - last_flip
            stats = update_frame_stats(stats, frame_s)
            if frame_s > SLOW_FRAME_S:
                log.warning("slow frame %d: %.1f ms", frame_index, frame_s * 1000)
            if has_vsync and pacing_ok(stats) is False:  # vsync claimed but frames are not ~60 per second
                log.error("vsync is not pacing frames (%.0f FPS): falling back to clock pacing; "
                          "timing is approximate, do not use this run for the gate", stats.frames / stats.total_s)
                has_vsync, stats = False, FrameStats()  # restart the stats so the summary reflects paced frames
        last_flip = now
        frame_index += 1
        if deadline is not None and now >= deadline:
            return stats


def fake_status_feed(q: queue.Queue, stop: threading.Event) -> None:
    """Fake ControlStatus for testing the dwell bars: dwell 1.5 s, move 1 s, stop 0.5 s, next arrow."""
    targets = [Target.FWD, Target.LEFT, Target.RIGHT, Target.BACK]
    start = time.monotonic()
    while not stop.is_set():
        elapsed = time.monotonic() - start
        target = targets[int(elapsed // 3.0) % len(targets)]
        phase = elapsed % 3.0
        if phase < 1.5:
            status = ControlStatus(State.DWELLING, target, phase / 1.5)
        elif phase < 2.5:
            status = ControlStatus(State.MOVING, target, 1.0)
        else:
            status = ControlStatus(State.STOPPED, Target.NONE, 0.0)
        offer_latest(q, status)
        stop.wait(0.05)  # this thread may sleep; only the render loop must not


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="SSVEP flicker screen")
    parser.add_argument("--single", type=float, default=None, help="one fullscreen target at this frequency")
    parser.add_argument("--fake-status", action="store_true", help="animate dwell bars with fake ControlStatus")
    parser.add_argument("--seconds", type=float, default=None, help="quit after this many seconds")
    parser.add_argument("--windowed", action="store_true", help="development only; the gate needs fullscreen")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None, start_events: list[str] | None = None,
         status_queue: queue.Queue | None = None) -> int:
    """start_events is for tests only: key names posted before the warning screen (e.g. ["space"])."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    args = parse_args(sys.argv[1:] if argv is None else argv)
    single_frames = None
    if args.single is not None:
        try:
            single_frames = frames_per_cycle(args.single)
        except ValueError as error:
            log.error("%s", error)
            return 2
    pygame.init()
    stop_feed = threading.Event()
    try:
        screen, has_vsync = open_display(args.windowed)
        pygame.display.set_caption("SSVEP flicker")
        clock = pygame.time.Clock()
        deadline = None if args.seconds is None else time.monotonic() + args.seconds
        for name in start_events or []:
            pygame.event.post(pygame.event.Event(pygame.KEYDOWN, key=KEYS[name]))
        if args.fake_status and status_queue is None:
            status_queue = queue.Queue(maxsize=1)
            threading.Thread(target=fake_status_feed, args=(status_queue, stop_feed), daemon=True).start()
        stats = FrameStats()
        if show_warning(screen, clock, deadline):
            stats = run_flicker(screen, clock, single_frames, has_vsync, deadline, status_queue)
    finally:
        stop_feed.set()
        pygame.quit()
    print(format_frame_summary(stats))  # the evidence line for PROGRESS.md
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
