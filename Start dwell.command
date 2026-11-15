#!/bin/bash
# Double-click in Finder to start the demo in "dwell" mode (see docs/COMMANDS.md).
cd "$(dirname "$0")"
./demo.sh dwell
echo
read -n 1 -s -r -p "Finished. Press any key to close this window."
