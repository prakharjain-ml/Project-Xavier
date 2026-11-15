#!/bin/bash
# Double-click in Finder to start the demo in "chair-dwell" mode (see docs/COMMANDS.md).
cd "$(dirname "$0")"
./demo.sh chair-dwell
echo
read -n 1 -s -r -p "Finished. Press any key to close this window."
