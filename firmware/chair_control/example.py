"""
example.py - first drive test. WHEELS IN THE AIR the first time, kill key in reach.

Run from anywhere:   python firmware/chair_control/example.py COM4
Expected: forward 2 s, spin left 1 s, backward 2 s, spin right 1 s, gentle right curve 2 s, stop.
"""
import sys

from chair import Chair   # works because Python adds this script's folder to the import path

port = sys.argv[1] if len(sys.argv) > 1 else "COM4"

with Chair(port) as chair:                 # opens the bridge; leaving the block always stops the chair
    print("forward");     chair.forward(200, 2)
    print("turn left");   chair.turn_left(150, 1)
    print("backward");    chair.backward(200, 2)
    print("turn right");  chair.turn_right(150, 1)
    print("curve right"); chair.drive(250, 150, 2)   # left wheel faster than right -> curves right
    print("bridge state:", chair.state, "| distance:", chair.distance_cm, "cm")
print("done, chair stopped")
