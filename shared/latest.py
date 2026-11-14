"""Latest-only queue helpers, shared by every process (no pygame, no cv2 here).

Producers (camera, gaze tracker, control loop) run faster or slower than their consumers; only the newest value
matters, so queues have maxsize=1 and old values are dropped instead of piling up as lag.
"""

from __future__ import annotations

from queue import Empty, Full


def offer_latest(q, item) -> None:
    """Put item into a maxsize=1 queue, replacing whatever is waiting. Never blocks."""
    try:
        q.get_nowait()
    except Empty:
        pass
    try:
        q.put_nowait(item)
    except Full:  # another producer refilled it in between; dropping this one is fine
        pass


def drain_newest(q, current):
    """Take everything waiting in q and return the newest item, or `current` if q was empty."""
    while True:
        try:
            current = q.get_nowait()
        except Empty:
            return current
