"""HUMAN ONLY: find the board's power self-hold (latch) pin.

Setup:  ST-Link on the board the POWER BUTTON plugs into: SWDIO, SWCLK, GND only (NO 3.3 V wire!).
        Charger plugged in (or battery). Wheels in the air. ESP32 USB unplugged. Close every OpenOCD window.
Run:    python find_hold_pin.py          (drives candidate pins HIGH)
        python find_hold_pin.py low      (only if the HIGH run finds nothing)

Each round: you press and HOLD the button, the script halts the chip and drives a few unused pins, you RELEASE.
Board turns off -> the pin is not in that group, next round. Board stays on -> it narrows to the exact pin.
"""
import os
import socket
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
LOW = "low" in [a.lower() for a in sys.argv[1:]]
START = next((int(a) for a in sys.argv[1:] if a.isdigit()), 1)   # e.g. "python find_hold_pin.py 2" starts at round 2

BASE = {"PA": 0x48000000, "PB": 0x48000400, "PC": 0x48000800, "PF": 0x48001400}
# Unused pins only. Never touched: motor PA8-10/PB13-15, halls PA0/PF1/PC15, UART PA2/PA3, VBATT PA4,
# current PA6, phase PB0/PB1, SWD PA13/PA14, PB6/PB7. Most likely first (what other boards use).
GROUPS = [
    ["PC13", "PB12", "PA5", "PA1"],
    ["PA7", "PA12", "PA15", "PB3"],
    ["PB4", "PB5", "PB8", "PB9"],
    ["PB10", "PB11", "PC14", "PF0"],
    ["PF6", "PF7", "PA11", "PB2"],
    ["PA6", "PB0", "PB1"],          # CURRENT_DC / PHASE_A / PHASE_B were copied from another layout, never verified
    ["PB6", "PB7"],                 # USART0 pins whose pads are not fitted
]


def find_openocd():
    for d in (os.path.join(HERE, "..", "tools", "xpack-openocd-0.12.0-7"),
              os.path.join(HERE, "..", "firmware_ref", "openocd_new", "xpack-openocd-0.12.0-7")):
        exe = os.path.join(d, "bin", "openocd.exe")
        if os.path.exists(exe):
            return exe, os.path.join(d, "openocd", "scripts")
    sys.exit("OpenOCD not found (same places as _openocd.bat looks).")


OCD_EXE, OCD_SCRIPTS = find_openocd()


class Ocd:
    def __init__(self):
        self.log = open(os.path.join(HERE, "find_hold_pin_openocd.log"), "a")
        self.p = subprocess.Popen(
            [OCD_EXE, "-s", OCD_SCRIPTS, "-f", "interface/stlink.cfg", "-c", "transport select swd",
             "-c", "set CPUTAPID 0", "-c", "set FLASH_SIZE 0x10000", "-f", "target/gd32e23x.cfg",
             "-f", "gd32e23x_tools.tcl", "-c", "init"],
            cwd=HERE, stdout=self.log, stderr=subprocess.STDOUT)
        self.s = None
        t0 = time.time()
        while time.time() - t0 < 10:
            if self.p.poll() is not None:
                break
            try:
                self.s = socket.create_connection(("127.0.0.1", 6666), timeout=5)
                break
            except OSError:
                time.sleep(0.3)

    def ok(self):
        return self.s is not None

    def cmd(self, c):
        try:
            self.s.sendall(c.encode() + b"\x1a")
            buf = b""
            while not buf.endswith(b"\x1a"):
                d = self.s.recv(4096)
                if not d:
                    break
                buf += d
            return buf.rstrip(b"\x1a").decode(errors="ignore").strip()
        except OSError:
            return ""

    def rd(self, a):
        try:
            return int(self.cmd(f"read_memory 0x{a:08X} 32 1").split()[0], 16)
        except (ValueError, IndexError):
            return None

    def close(self):
        try:
            if self.s:
                self.s.close()
        except OSError:
            pass
        self.p.kill()
        self.p.wait()
        self.log.close()


def pin(name):
    return BASE[name[:2]], int(name[2:])


def drive(o, name):
    b, n = pin(name)
    o.cmd(f"mww 0x{b + 0x18:08X} 0x{(1 << (n + 16)) if LOW else (1 << n):08X}")   # output level first (BOP)
    o.cmd(f"mmw 0x{b:08X} 0x{1 << (2 * n):08X} 0x{3 << (2 * n):08X}")              # then mode = output


def release(o, name):
    b, n = pin(name)
    o.cmd(f"mmw 0x{b:08X} 0 0x{3 << (2 * n):08X}")                                 # back to input (floating)


def driven(o, name):
    """True if the chip still answers AND the pin is still set up the way we left it (no power loss / reset)."""
    b, n = pin(name)
    ctl, octl = o.rd(b), o.rd(b + 0x14)
    if ctl is None or octl is None:
        return False
    return (ctl >> (2 * n) & 3) == 1 and bool(octl >> n & 1) != LOW


def chip_alive(o, check_pins, tries=6):
    """Several reads because the SWD link is glitchy: alive if at least 2 reads look right."""
    good = 0
    for _ in range(tries):
        if all(driven(o, p) for p in check_pins):
            good += 1
        time.sleep(0.3)
    return good >= 2


def start_round():
    """Board must be ON (button held). Start OpenOCD, halt the chip (all pins -> inputs, motors off)."""
    while True:
        o = Ocd()
        if o.ok():
            r = o.cmd("reset halt")
            if "halted" in r.lower() or o.rd(0x48000000) is not None:
                o.cmd("mmw 0x40021014 0x004E0000 0")        # GPIO A/B/C/F clocks on
                return o
        o.close()
        input("   Could not reach the chip. Keep HOLDING the button, check SWDIO/SWCLK/GND, press Enter to retry ")


def main():
    level = "LOW" if LOW else "HIGH"
    print(f"Self-hold pin finder - driving candidate pins {level}. {len(GROUPS)} rounds max.\n")
    i = START - 1
    while i < len(GROUPS):
        group = GROUPS[i]
        print(f"=== Round {i + 1}/{len(GROUPS)}: {', '.join(group)} ===")
        print(">>> Press and HOLD the power button now (keep holding) ...")
        for s in range(5, 0, -1):
            print(f"   starting in {s} ...")
            time.sleep(1)
        o = start_round()
        for p in group:
            drive(o, p)
        if not chip_alive(o, group, tries=3):
            print("   Pins did not stick (glitchy link?) - repeating this round.\n")
            o.close()
            continue
        input(">>> RELEASE the button now, take your hand away, THEN press Enter ")
        print("   checking in 4 s ...")
        time.sleep(4)
        if not chip_alive(o, group):
            print("   Board turned OFF -> hold pin is not in this group.\n")
            o.close()
            i += 1
            continue
        print("   Board STAYED ON! One of these pins holds the power. Narrowing down (hands off) ...")
        found = None
        for k, p in enumerate(group):
            release(o, p)
            time.sleep(4)
            still = group[k + 1:]
            alive = chip_alive(o, still[:1], tries=4) if still else chip_alive_any(o)
            if not alive:
                found = p
                break
            print(f"   {p}: not it (board still on)")
        o.close()
        if found:
            msg = f"SELF_HOLD = {found}  (active {level})"
            print(f"\n*********** FOUND: {msg} ***********")
            print("Board is off now. Tell Claude this line.")
            with open(os.path.join(HERE, "hold_pin_result.txt"), "w") as f:
                f.write(msg + "\n")
        else:
            print("\nBoard stayed on even with all pins released - strange. Tell Claude what you saw.")
        return
    print(f"\nNo pin held the power when driven {level}." + ("" if LOW else " Run:  python find_hold_pin.py low"))


def chip_alive_any(o):
    good = 0
    for _ in range(4):
        if o.rd(0x48000000) is not None and o.rd(0x40021014) is not None:
            good += 1
        time.sleep(0.3)
    return good >= 2


if __name__ == "__main__":
    main()
