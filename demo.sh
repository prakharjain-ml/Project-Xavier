#!/bin/bash
# One-word launcher for the demo, so nobody has to type long commands under pressure.
#
#   ./demo.sh dwell    eyes + objects, confirm by looking 1.5 s (no headset)
#   ./demo.sh jaw      eyes + objects, confirm by jaw clench (headset on its Wi-Fi)
#   ./demo.sh mock     jaw + route following + chevrons, motor commands to a FAKE port (nothing moves)
#   ./demo.sh chair    jaw + route following on the REAL hoverboard (wheels up first, kill key in hand)
#   ./demo.sh chair-dwell   as chair, but confirm by looking (backup if the headset fails)
#   ./demo.sh preview  mouse preview of the route (no eyes, no headset, no motors)
#
# Cameras: laptop camera = 1 (eyes), Pixel = 0 (room), as on every run so far. If the calibration shows the room
# instead of your face, swap them:  EYE_CAM=0 ROOM_CAM=1 ./demo.sh jaw
# Add --skip-calibration (or any other option) after the mode to pass it through:  ./demo.sh jaw --skip-calibration
set -euo pipefail
cd "$(dirname "$0")"
source "$HOME/venvs/hp26/bin/activate"

EYE_CAM="${EYE_CAM:-1}"
ROOM_CAM="${ROOM_CAM:-0}"
CAMS=(--eye-camera "$EYE_CAM" --source "$ROOM_CAM")
JAW=(--confirm jaw --jaw-board wifi --jaw-channels "${JAW_CHANNELS:-1,2}")
ROUTE=(--follow route --cam-height "${CAM_HEIGHT:-0.89}" --cam-pitch "${CAM_PITCH:-0}")

esp32_port() {
  local port
  port=$(ls /dev/cu.usbmodem* 2>/dev/null | head -1 || true)
  if [ -z "$port" ]; then
    echo "No ESP32 found (no /dev/cu.usbmodem*). Plug it in by USB and close the Arduino Serial Monitor." >&2
    exit 2
  fi
  echo "$port"
}

need_pixel() {
  # The Pixel's webcam mode drops off often. Without it there is only one camera, so "camera 1" does not exist
  # and the eye tracker fails with "cannot open camera 1". Check first and say what to do.
  if ! system_profiler SPCameraDataType 2>/dev/null | grep -q "Android Webcam"; then
    echo "The Pixel is not connected as a webcam (macOS only sees: $(system_profiler SPCameraDataType 2>/dev/null | grep -E '^ +[A-Za-z].*:$' | tr -d ':' | xargs))." >&2
    echo "Fix: unplug the Pixel, plug it straight into the laptop, unlock it, choose 'Webcam' in the USB menu, keep the screen on." >&2
    echo "Then run this command again." >&2
    exit 2
  fi
}

need_headset_wifi() {
  # The headset's Wi-Fi shield is only reachable from its own network, where the laptop gets a 192.168.4.x address.
  if ! ifconfig 2>/dev/null | grep -q "inet 192\.168\.4\."; then
    echo "The laptop is not on the headset's Wi-Fi, so the jaw clench cannot be read." >&2
    echo "Fix: quit the OpenBCI GUI (Cmd+Q), then join the 'OpenBCI-xxxx' Wi-Fi network and run this again." >&2
    echo "(No headset right now? Use the dwell version instead: Start dwell.command or Start chair-dwell.command.)" >&2
    exit 2
  fi
  if pgrep -f OpenBCI_GUI >/dev/null; then
    echo "The OpenBCI GUI is still open and holds the headset. Quit it (Cmd+Q) and run this again." >&2
    exit 2
  fi
}

mode="${1:-}"
shift || true
case "$mode" in dwell|jaw|mock|chair|chair-dwell|preview) need_pixel ;; esac
case "$mode" in jaw|mock|chair) need_headset_wifi ;; esac
case "$mode" in
  dwell)       exec python -m vision.object_select --confirm dwell "${CAMS[@]}" "$@" ;;
  jaw)         exec python -m vision.object_select "${JAW[@]}" "${CAMS[@]}" "$@" ;;
  mock)        exec python -m vision.object_select "${JAW[@]}" "${CAMS[@]}" --drive --mock "${ROUTE[@]}" "$@" ;;
  chair)       exec python -m vision.object_select "${JAW[@]}" "${CAMS[@]}" --drive --serial "$(esp32_port)" "${ROUTE[@]}" "$@" ;;
  chair-dwell) exec python -m vision.object_select --confirm dwell "${CAMS[@]}" --drive --serial "$(esp32_port)" "${ROUTE[@]}" "$@" ;;
  preview)     exec python -m vision.nav_preview --source "$ROOM_CAM" "$@" ;;
  *)
    sed -n '2,13p' "$0" | sed 's/^# \{0,1\}//'
    exit 1 ;;
esac
