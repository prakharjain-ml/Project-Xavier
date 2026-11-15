"""HUMAN ONLY: PA7 alone does not keep the power on with the firmware running. Find the second pin.
Setup: same as hold_check.py (ST-Link on button board, SWDIO/SWCLK/GND only, charger in, no other OpenOCD).
Run:   python hold_test2.py   - hold the button during each countdown, release when told.

Test A (firmware running): add PA12, PA15, PB3 HIGH (they were HIGH together with PA7 when the board stayed on).
Test B (only if A fails): chip halted, ONLY PA7 HIGH - does PA7 alone hold?
"""
import time

import find_hold_pin as f

EXTRA = ["PA12", "PA15", "PB3"]


def countdown(msg):
    print(f"\n>>> {msg}: press and HOLD the power button now (keep holding until RELEASE is shown)")
    for s in range(5, 0, -1):
        print(f"   starting in {s} ...")
        time.sleep(1)


def connect():
    while True:
        o = f.Ocd()
        if o.ok() and o.rd(0x48000000) is not None:
            o.cmd("mmw 0x40021014 0x004E0000 0")
            return o
        o.close()
        countdown("Could not reach the chip - check SWD wires. Retrying")


def release_and_check(o, pins):
    print(">>> RELEASE the button now. Hands off. Checking in 6 s ...")
    time.sleep(6)
    return f.chip_alive(o, pins)


# ---------- Test A ----------
countdown("Test A")
o = connect()
for p in EXTRA:
    f.drive(o, p)
if release_and_check(o, ["PA7"] + EXTRA):
    print("   Board STAYED ON with PA7 + PA12/PA15/PB3. Finding which one is needed (hands off) ...")
    needed = None
    for k, p in enumerate(EXTRA):
        f.release(o, p)
        time.sleep(4)
        if not f.chip_alive(o, ["PA7"] + EXTRA[k + 1:], tries=4):
            needed = p
            break
        print(f"   {p}: not needed (board still on)")
    o.close()
    if needed:
        print(f"\n*********** FOUND: second hold pin = {needed} (HIGH), together with PA7 ***********")
    else:
        print("\nBoard stayed on with all three released again - tell Claude.")
    raise SystemExit
o.close()
print("   Test A: board turned OFF.")

# ---------- Test B ----------
countdown("Test B")
o = f.start_round()          # halts the chip: all pins inputs, motors off
f.drive(o, "PA7")
alive = release_and_check(o, ["PA7"])
o.close()
print("\n*********** Test B: PA7 alone (chip halted) ->",
      "board STAYED ON: the running firmware turns something off ***********" if alive else
      "board turned OFF: PA7 alone is not enough ***********")
print("Paste all of this to Claude.")
