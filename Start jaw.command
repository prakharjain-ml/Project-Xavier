#!/bin/bash
# Double-click in Finder to start the demo in "jaw" mode (see docs/COMMANDS.md).
cd "$(dirname "$0")"
./demo.sh jaw
echo
read -n 1 -s -r -p "Finished. Press any key to close this window."
