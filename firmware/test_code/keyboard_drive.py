"""
keyboard_drive.py - drive the wheelchair with the arrow keys (HUMAN ONLY, Windows).

Run:     python firmware/test_code/keyboard_drive.py 400            speed 400, port COM4
         python firmware/test_code/keyboard_drive.py 400 COM5       other port

Keys (HOLD them - the chair only moves while a key is held, like a dead-man switch):
    Up            forward
    Down          backward
    Left / Right  spin in place (at half the speed)
    Up + Left     curve left while driving forward   (also Up+Right, Down+Left, Down+Right)
    Space         stop
    Esc or Q      quit (the chair stops)

Safety:
    - Let go of all keys -> immediate stop.
    - Keys only count while THIS terminal window is in front. Click another window -> the chair stops.
    - Script crash / Ctrl+C / laptop unplugged -> the ESP32 stops the wheels within 200 ms.
    - Speed is capped at 850 by the chair library, whatever you type.
    - First time: WHEELS IN THE AIR. Kill key in reach.

Uses the library in ../chair_control (class Chair; docs: firmware/chair_control/README.md). Close the Arduino Serial Monitor first (it blocks the port).
"""
import ctypes
import msvcrt
import os
import sys
import time

# Make "from chair import Chair" work: the library lives in the sibling folder chair_control/
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "chair_control"))
from chair import Chair, DEFAULT_MAX_SPEED  # noqa: E402

LOOP_S = 0.05            # read keys 20x per second
TURN_FACTOR = 0.5        # spinning in place uses this fraction of the speed (full speed spins are violent)
CURVE_FACTOR = 0.4       # while curving, the inner wheel runs at this fraction of the speed

# Windows virtual-key codes
VK_LEFT, VK_UP, VK_RIGHT, VK_DOWN = 0x25, 0x26, 0x27, 0x28
VK_SPACE, VK_ESCAPE, VK_Q = 0x20, 0x1B, 0x51


def mix(up, down, left, right, speed):
    """Turn the held arrow keys into (left_wheel, right_wheel) speeds. Positive = forward."""
    fwd = int(up) - int(down)        # +1 forward, -1 backward, 0 none (both held cancel out)
    turn = int(right) - int(left)    # +1 right, -1 left, 0 none
    if fwd and turn:                 # curve: slow down the wheel on the inside of the turn
        outer, inner = fwd * speed, int(fwd * speed * CURVE_FACTOR)
        return (outer, inner) if turn > 0 else (inner, outer)
    if fwd:                          # straight
        return fwd * speed, fwd * speed
    if turn:                         # spin in place
        s = int(speed * TURN_FACTOR)
        return turn * s, -turn * s
    return 0, 0


def main():
    if len(sys.argv) < 2 or not sys.argv[1].isdigit():
        print(__doc__)
        sys.exit("Give a speed, e.g.:  python firmware/test_code/keyboard_drive.py 400")
    speed = int(sys.argv[1])
    port = sys.argv[2] if len(sys.argv) > 2 else "COM4"
    if speed > DEFAULT_MAX_SPEED:
        print(f"Speed {speed} is above the library cap - it will be limited to {DEFAULT_MAX_SPEED}.")
        speed = DEFAULT_MAX_SPEED

    user32 = ctypes.windll.user32
    my_window = user32.GetForegroundWindow()     # the terminal you started this from (it is in front right now)

    def held(vk):
        """True while the key is physically held down."""
        return bool(user32.GetAsyncKeyState(vk) & 0x8000)

    print(f"Connecting to the chair on {port} ...")
    with Chair(port) as chair:
        print(f"\nREADY. Speed {speed} (spin {int(speed * TURN_FACTOR)}). Hold arrow keys to drive. "
              f"Space = stop, Esc/Q = quit.\n")
        last = None
        while True:
            # swallow the key presses so they do not pile up in the terminal after the script ends
            while msvcrt.kbhit():
                msvcrt.getwch()

            focused = user32.GetForegroundWindow() == my_window
            if focused and (held(VK_ESCAPE) or held(VK_Q)):
                break

            if not focused or held(VK_SPACE):
                l, r = 0, 0
            else:
                l, r = mix(held(VK_UP), held(VK_DOWN), held(VK_LEFT), held(VK_RIGHT), speed)

            if (l, r) != last:                     # only change the command when the keys change
                if l == 0 and r == 0:
                    chair.stop()                   # stop is immediate (no ramp)
                else:
                    chair.drive(l, r)              # no seconds -> keeps going until the next change
                last = (l, r)

            note = "" if focused else "  (window not in front -> stopped)"
            print(f"\r  left {l:5d}  right {r:5d}  | bridge {chair.state:<8} {note:<40}", end="", flush=True)
            time.sleep(LOOP_S)

    while msvcrt.kbhit():
        msvcrt.getwch()
    print("\nQuit - chair stopped.")


if __name__ == "__main__":
    main()
