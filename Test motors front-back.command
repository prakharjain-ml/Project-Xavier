#!/bin/bash
# Double-click to test the motors only: forward at 200 for 2 s, stop 1 s, backward at 200 for 2 s, stop.
# WHEELS IN THE AIR, kill key in reach. Uses Keshav's firmware/chair_control library (talks to the ESP32 bridge).
cd "$(dirname "$0")"
source "$HOME/venvs/hp26/bin/activate"
PORT="${ESP32_PORT:-$(ls /dev/cu.wchusbserial* /dev/cu.usbserial-* /dev/cu.usbmodem* 2>/dev/null | head -1)}"
if [ -z "$PORT" ]; then echo "No ESP32 found: plug it into its COM port with a data cable."; read -n 1 -s -r; exit 2; fi
echo "ESP32 port: $PORT"
python - "$PORT" <<'PY'
import sys, time
sys.path.insert(0, "firmware/chair_control")
from chair import Chair
with Chair(sys.argv[1]) as chair:          # leaving this block always stops the wheels
    print("bridge state:", chair.state, "| distance:", chair.distance_cm, "cm")
    print("FORWARD 200 for 2 s");  chair.forward(200, 2)
    time.sleep(1)
    print("BACKWARD 200 for 2 s"); chair.backward(200, 2)
    print("bridge state:", chair.state, "| distance:", chair.distance_cm, "cm")
print("done, wheels stopped")
PY
echo
read -n 1 -s -r -p "Finished. Press any key to close this window."
