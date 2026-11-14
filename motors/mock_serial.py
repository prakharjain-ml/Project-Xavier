"""A fake serial port with the small part of the pyserial API the driver uses. For tests and `app.py --mock`."""

from __future__ import annotations

import threading


class MockSerialError(OSError):
    """pyserial's SerialException is an OSError too, so the driver catches both the same way."""


class MockSerial:
    def __init__(self, replies: list[str] | None = None, fail_after_writes: int | None = None) -> None:
        self._lock = threading.Lock()
        self._written: list[str] = []
        self._rx = bytearray("".join(replies or []).encode())
        self._fail_after = fail_after_writes
        self.closed = False

    @property
    def in_waiting(self) -> int:
        with self._lock:
            return len(self._rx)

    def read(self, size: int = 1) -> bytes:
        with self._lock:
            chunk, self._rx = bytes(self._rx[:size]), self._rx[size:]
            return chunk

    def write(self, data: bytes) -> int:
        with self._lock:
            if self.closed or (self._fail_after is not None and len(self._written) >= self._fail_after):
                raise MockSerialError("mock port unplugged")
            self._written.append(data.decode())
            return len(data)

    def feed(self, line: str) -> None:
        """Queue a reply as if the bridge had sent it."""
        with self._lock:
            self._rx.extend(line.encode())

    def close(self) -> None:
        self.closed = True

    def lines(self) -> list[str]:
        """Every line written so far, without the newline."""
        with self._lock:
            return [line.rstrip("\n") for line in self._written]
