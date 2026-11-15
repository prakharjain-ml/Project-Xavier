"""HUMAN ONLY bench test: laptop -> ESP32 bridge -> hoverboard, wheels IN THE AIR, kill switch in hand.

Speaks the docs/INTERFACES.md bridge protocol (C,<seq>,<left>,<right> every 50 ms) so it exercises the same path as
motors/driver.py, and prints the bridge's D,<distance_cm>,<state> lines.

Usage:  python firmware/hoverboard/tools/bridge_bench_test.py COM5 [speed]   (Windows; see Device Manager -> Ports)
        python firmware/hoverboard/bridge_bench_test.py /dev/cu.usbmodemXXXX   (macOS)
Sequence: stop 1 s, forward 80 for 3 s, stop 2 s, back 80 for 3 s, stop 2 s, turn left 80 for 3 s, stop.
Then it goes silent for 1 s: the bridge must report WATCHDOG and the wheels must stop.
"""
import sys
import threading
import time

import serial  # pyserial

port = sys.argv[1] if len(sys.argv) > 1 else "COM5"
V = int(sys.argv[2]) if len(sys.argv) > 2 else 80   # optional speed, e.g. 120 if the wheel does not move
ser = serial.Serial(port, 115200, timeout=0.1)
time.sleep(3)  # ESP32 may reboot when the port opens; gives it time to find the boards
seq = 0
last_status = ""


def reader():
    global last_status
    while True:
        try:
            line = ser.readline().decode(errors="ignore").strip()
        except serial.SerialException:
            return
        if line.startswith("#"):
            print("   ESP32:", line)      # board found / lost messages
        elif line:
            last_status = line


threading.Thread(target=reader, daemon=True).start()


def drive(left, right, seconds, label):
    global seq
    print(f"{label:<22} left={left:>4} right={right:>4} for {seconds} s")
    t_end = time.time() + seconds
    while time.time() < t_end:
        ser.write((f"C,{seq},{left},{right}\n" if (left or right) else f"S,{seq}\n").encode())
        seq += 1
        time.sleep(0.05)
    print(f"{'':<22} bridge says: {last_status}")


try:
    print("WHEELS IN THE AIR? Starting in 3 s (Ctrl+C to abort)")
    time.sleep(3)
    drive(0, 0, 1, "stop")
    if len(sys.argv) > 3 and sys.argv[3] == "hold":     # debug: keep driving forward for 60 s
        drive(V, V, 60, "HOLD forward 60 s")
        raise SystemExit
    drive(V, V, 3, "forward")
    drive(0, 0, 2, "stop")
    drive(-V, -V, 3, "backward")
    drive(0, 0, 2, "stop")
    drive(-V, V, 3, "turn in place (left)")
    drive(0, 0, 1, "stop")
    print("silence for 1 s (watchdog test) ...")
    time.sleep(1.0)
    print(f"{'':<22} bridge says: {last_status}   (expect WATCHDOG)")
finally:
    for _ in range(5):
        ser.write(f"S,{seq}\n".encode())
        seq += 1
        time.sleep(0.05)
    print("done, sent stop")
