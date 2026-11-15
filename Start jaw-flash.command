#!/bin/bash
# Double-click in Finder: headset-only jaw test over the OpenBCI Wi-Fi (black screen, WHITE flash on each clench).
# See docs/COMMANDS.md.
cd "$(dirname "$0")"
PY="$HOME/venvs/hp26/bin/python"  # the project Python (has numpy, pygame, brainflow); never the system one
pkill -f OpenBCI_GUI 2>/dev/null && echo "Closed the OpenBCI GUI (it would hold the headset)." && sleep 2
# The Wi-Fi shield is only reachable from its own network, where the laptop gets a 192.168.4.x address.
if ! ifconfig 2>/dev/null | grep -q "inet 192\.168\.4\."; then
  echo "Join the 'OpenBCI-xxxx' Wi-Fi now (menu bar Wi-Fi icon). This window starts the test as soon as you do..."
  until ifconfig 2>/dev/null | grep -q "inet 192\.168\.4\."; do sleep 1; done
  echo "On the headset Wi-Fi. Starting."
  sleep 2
fi
"$PY" -m tools.jaw_flash --channels "${JAW_CHANNELS:-1,2}"
echo
read -n 1 -s -r -p "Finished. Press any key to close this window."
