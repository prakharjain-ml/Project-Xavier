#!/bin/bash
# Double-click: demo in "chair-blink" mode (see docs/COMMANDS.md). Calibrates the eyes first.
cd "$(dirname "$0")"
./demo.sh chair-blink
echo
read -n 1 -s -r -p "Finished. Press any key to close this window."
