#!/bin/bash
# Double-click in Finder to start the demo in "mock-key" mode (see docs/COMMANDS.md).
cd "$(dirname "$0")"
./demo.sh mock-key
echo
read -n 1 -s -r -p "Finished. Press any key to close this window."
