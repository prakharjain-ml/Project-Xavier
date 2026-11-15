#!/bin/bash
# Double-click in Finder to start the demo in "chair-key" mode (see docs/COMMANDS.md).
cd "$(dirname "$0")"
./demo.sh chair-key
echo
read -n 1 -s -r -p "Finished. Press any key to close this window."
