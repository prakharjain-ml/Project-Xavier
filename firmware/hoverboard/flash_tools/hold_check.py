"""HUMAN ONLY: check why the board does not stay on. Does NOT halt or change anything, only reads.
Setup: ST-Link on the button board (SWDIO, SWCLK, GND, no 3.3 V), charger in, close other OpenOCD windows.
Run:   python hold_check.py      then HOLD the button when asked, release when asked.
"""
import os
import time

from find_hold_pin import HERE, Ocd

NEW = open(os.path.join(HERE, "e235_single_usart1_hold.bin"), "rb").read()
OLD = open(os.path.join(HERE, "e235_single_usart1.bin"), "rb").read()
GPIOA = 0x48000000


def word(b, off):
    return int.from_bytes(b[off:off + 4], "little")


def snapshot(o):
    ctl, octl, istat = o.rd(GPIOA), o.rd(GPIOA + 0x14), o.rd(GPIOA + 0x10)
    ibug, spd = o.rd(0x20000130), o.rd(0x20000144)
    pc = o.cmd("reg pc")
    if ctl is None:
        return "no answer from chip"
    mode = ["input", "OUTPUT", "alt", "analog"][ctl >> 14 & 3]
    return (f"PA7 mode={mode} out={'HIGH' if octl >> 7 & 1 else 'low'} reads={'HIGH' if istat >> 7 & 1 else 'low'}"
            f" | iBug={None if ibug is None else ibug & 0xFF} speed={spd}")


print(">>> Press and HOLD the power button now (keep holding until RELEASE is shown)")
for s in range(5, 0, -1):
    print(f"   starting in {s} ...")
    time.sleep(1)
o = Ocd()
if not o.ok():
    o.close()
    raise SystemExit("Could not start OpenOCD / reach the chip. Check the SWD wires and try again.")

f = [o.rd(0x08000000 + off) for off in (244, 260, 272)]
if f == [word(NEW, x) for x in (244, 260, 272)]:
    print("Flash contains: NEW firmware (option 5, PA7 hold)")
elif f == [word(OLD, x) for x in (244, 260, 272)]:
    print("Flash contains: OLD firmware (option 1) -> option 5 was not flashed")
else:
    print("Flash contains: something else / unreadable:", f)

for _ in range(5):
    print("  holding: ", snapshot(o))
    time.sleep(0.5)
print(">>> RELEASE the button now")
t0 = time.time()
while time.time() - t0 < 6:
    print(f"  released {time.time() - t0:4.1f}s: ", snapshot(o))
    time.sleep(0.4)
o.close()
print("done - paste all of this to Claude")
