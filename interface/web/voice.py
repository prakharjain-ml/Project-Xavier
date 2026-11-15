"""Spoken announcements so people nearby (and the judges) hear what the chair is about to do.

Clips are the team's Amazon Polly recordings in "Voice Recordings/" (named by exactly what they say). They play
locally with macOS `afplay`, so they work offline (the laptop has no internet on the OpenBCI Wi-Fi). An event
without a clip falls back to the Mac's own voice (`say`) so nothing is silent. Playback never blocks the session:
one announcement at a time, a newer one replaces an older one, and the same phrase is not repeated within
REPEAT_S. Announcing is information only; it never affects motion.
"""

from __future__ import annotations

import logging
import subprocess
import threading
import time
from pathlib import Path

log = logging.getLogger("interface.web.voice")

CLIPS_DIR = Path(__file__).resolve().parents[2] / "Voice Recordings"
REPEAT_S = 3.0

# event -> (clip file name, words to say if the clip is missing)
PHRASES: dict[str, tuple[str | None, str]] = {
    "manual_FWD": ("Moving Forward.mp3", "Moving forward"),
    "manual_BACK": ("Reversing.mp3", "Reversing"),
    "manual_LEFT": ("Turning to the left.mp3", "Turning to the left"),
    "manual_RIGHT": (None, "Turning to the right"),  # no clip yet: the Mac voice says it
    "drive_chair": ("Driving to the chair.mp3", "Driving to the chair"),
    "drive_dining table": ("Driving to the table.mp3", "Driving to the table"),
    "confirmed": ("Destination Confirmed .mp3", "Destination confirmed"),
    "driving": ("Driving to the destination.mp3", "Driving to the destination"),
    "planning": ("Planning Route.mp3", "Planning route"),
    "no_route": ("No Safe Route.mp3", "No safe route"),
    "arrived": ("Arrived.mp3", "Arrived"),
    "stop": ("Stopping.mp3", "Stopping"),
    "estop": ("Stopping.mp3", "Stopping"),
}


class Voice:
    def __init__(self, clips_dir: Path = CLIPS_DIR) -> None:
        self._dir = clips_dir
        self._lock = threading.Lock()
        self._process: subprocess.Popen | None = None
        self._last: dict[str, float] = {}

    def command(self, event: str) -> list[str]:
        """The player command for an event: the Polly clip if present, else the Mac voice."""
        clip, words = PHRASES.get(event, (None, event.replace("_", " ")))
        if clip is not None and (self._dir / clip).is_file():
            return ["afplay", str(self._dir / clip)]
        return ["say", "-r", "190", words]

    def announce(self, event: str) -> None:
        now = time.monotonic()
        with self._lock:
            if now - self._last.get(event, -REPEAT_S) < REPEAT_S:
                return  # just said it: do not stutter while the state flickers
            self._last[event] = now
            if self._process is not None and self._process.poll() is None:
                self._process.terminate()  # the newest event matters more than finishing the old phrase
            try:
                self._process = subprocess.Popen(self.command(event), stdout=subprocess.DEVNULL,
                                                 stderr=subprocess.DEVNULL)
            except OSError as error:  # no audio tool: carry on silently, never stop the chair over sound
                log.warning("could not play %s: %s", event, error)

    def destination(self, label: str) -> bool:
        """Announce a confirmed destination. True if the clip already names where it is going."""
        named = f"drive_{label}" in PHRASES
        self.announce(f"drive_{label}" if named else "confirmed")
        return named


class SilentVoice(Voice):
    """For tests: records what would have been said."""

    def __init__(self) -> None:
        super().__init__()
        self.said: list[str] = []

    def announce(self, event: str) -> None:
        self.said.append(event)
