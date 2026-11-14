"""Find the hall-sensor pins of a hoverboard board by turning the wheel by hand.

How: OpenOCD must be running (8_openocd_server.bat or 4_autodetect_console.bat). This script reads the GPIO input
registers of the GD32E23x (GPIOA/B/C/F ISTAT) through OpenOCD's Tcl port 6666 for N seconds while you turn the wheel
slowly in ONE direction. Hall sensor pins toggle ~the same number of times; motor PWM pins (PA8-10, PB13-15) and
PB0/PB1 toggle much more and are not halls. Read-only: nothing is written to the chip.

Usage:  python hall_watch.py [seconds]          (default 20)
Master board result (2026-11-14): PA0, PF1, PC15 ~210 toggles each -> layout 2-3-9 uses HALL_A=PF1 HALL_B=PA0 HALL_C=PC15.
"""
import collections
import socket
import sys
import time

SECONDS = float(sys.argv[1]) if len(sys.argv) > 1 else 20.0
PORTS = {"A": 0x48000010, "B": 0x48000410, "C": 0x48000810, "F": 0x48001410}  # GPIOx_ISTAT
SKIP = {("A", 13), ("A", 14)}  # SWD pins
NOT_HALL = {("A", 8), ("A", 9), ("A", 10), ("B", 13), ("B", 14), ("B", 15), ("B", 0), ("B", 1)}  # PWM / phase current

s = socket.create_connection(("127.0.0.1", 6666), timeout=5)


def cmd(c):
    s.sendall(c.encode() + b"\x1a")
    b = b""
    while not b.endswith(b"\x1a"):
        b += s.recv(65536)
    return b[:-1].decode("latin-1")


def sample():
    vals = {}
    for p, a in PORTS.items():
        try:
            vals[p] = int(cmd(f"read_memory {a:#x} 32 1").strip(), 16) & 0xFFFF
        except ValueError:  # glitchy SWD read -> skip this port this time
            vals[p] = None
    return vals


print(f"Turn the wheel slowly in ONE direction now, for {SECONDS:.0f} s ...")
last_good, prev, toggles, history = {}, {}, collections.Counter(), []
t_end = time.time() + SECONDS
while time.time() < t_end:
    vals = sample()
    for p, v in vals.items():
        if v is None:
            continue
        if prev.get(p) == v:  # accept a value only if two reads in a row agree (glitch filter)
            if p in last_good and last_good[p] != v:
                for bit in range(16):
                    if (last_good[p] ^ v) >> bit & 1 and (p, bit) not in SKIP:
                        toggles[(p, bit)] += 1
            last_good[p] = v
        prev[p] = v
    history.append(dict(last_good))

cands = [(pb, c) for pb, c in toggles.most_common() if pb not in NOT_HALL]
print("\nAll toggling pins:", ", ".join(f"P{p}{b}={c}" for (p, b), c in toggles.most_common(14)))
top = cands[:3]
print("Hall candidates   :", ", ".join(f"P{p}{b}={c}" for (p, b), c in top))
if len(top) == 3:
    seq = []
    for snap in history:
        h = tuple((snap.get(p, 0) >> b) & 1 for (p, b), _ in top)
        if not seq or seq[-1] != h:
            seq.append(h)
    print("State sequence    :", " ".join("".join(map(str, x)) for x in seq[:40]))
    print("Expect a repeating cycle of 6 states, never 111 (000 may flash by between reads).")
