"""What the launcher offers, and read-only checks of what is plugged in.

Every mode runs the same command a human would type (`./demo.sh <mode>` or the headset test), so the launcher adds
no new behaviour: it is a front door. Readiness checks mirror demo.sh's own checks and never open a port.
"""

from __future__ import annotations

import glob
import subprocess
import sys
from dataclasses import dataclass

HEADSET, ROOM_CAMERA, CHAIR = "headset", "room camera", "chair controller"


@dataclass(frozen=True)
class Mode:
    key: str                     # demo.sh mode name (or "headset-test")
    title: str
    blurb: str                   # one line: what the rider does
    icon: str                    # interface.theme icon name
    needs: tuple[str, ...]       # readiness items this mode depends on
    live: bool                   # True = the real wheels can move: asks for confirmation first

    def command(self) -> list[str]:
        if self.key == "headset-test":
            return [sys.executable, "-m", "tools.jaw_flash"]
        return ["./demo.sh", self.key]


PRACTICE: tuple[Mode, ...] = (
    Mode("dwell", "Look to choose", "Look at an object for 1.5 s to pick it", "eye", (ROOM_CAMERA,), False),
    Mode("jaw", "Look + jaw clench", "Look at an object, clench to confirm", "jaw", (ROOM_CAMERA, HEADSET), False),
    Mode("mock", "Full drive, no motors", "Jaw confirm and route, to a fake chair", "route",
         (ROOM_CAMERA, HEADSET), False),
    Mode("mock-blink", "Blink twice", "Look, then blink twice to confirm", "blink", (ROOM_CAMERA,), False),
    Mode("mock-key", "Keyboard confirm", "Look, then press SPACE to confirm", "keyboard", (ROOM_CAMERA,), False),
    Mode("preview", "Route preview", "Point with the mouse, see the route", "target", (ROOM_CAMERA,), False),
    Mode("headset-test", "Headset test", "Black screen flashes on each clench", "pulse", (HEADSET,), False),
)

LIVE: tuple[Mode, ...] = (
    Mode("chair", "Chair · jaw", "Real wheels, confirm by clenching", "jaw", (ROOM_CAMERA, HEADSET, CHAIR), True),
    Mode("chair-blink", "Chair · blink", "Real wheels, blink twice to confirm", "blink", (ROOM_CAMERA, CHAIR), True),
    Mode("chair-key", "Chair · keyboard", "Real wheels, SPACE to confirm", "keyboard", (ROOM_CAMERA, CHAIR), True),
    Mode("chair-dwell", "Chair · look", "Real wheels, look 1.5 s to confirm", "eye", (ROOM_CAMERA, CHAIR), True),
)

ALL_MODES: tuple[Mode, ...] = PRACTICE + LIVE


def _run(args: list[str]) -> str:
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def headset_ready() -> bool:
    """On the headset's own Wi-Fi (the laptop gets 192.168.4.x), as demo.sh checks."""
    return "inet 192.168.4." in _run(["ifconfig"])


def room_camera_ready() -> bool:
    """A second camera besides the laptop's own (the Pixel webcam)."""
    out = _run(["system_profiler", "SPCameraDataType"])
    cameras = [line for line in out.splitlines()
               if line.startswith("    ") and not line.startswith("      ") and line.rstrip().endswith(":")]
    return len(cameras) >= 2


def chair_ready() -> bool:
    """An ESP32 USB serial port is present (demo.sh's search; listing only, nothing is opened)."""
    return bool(glob.glob("/dev/cu.wchusbserial*") or glob.glob("/dev/cu.usbmodem*"))


def readiness() -> dict[str, bool]:
    return {HEADSET: headset_ready(), ROOM_CAMERA: room_camera_ready(), CHAIR: chair_ready()}
