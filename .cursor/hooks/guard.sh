#!/bin/bash
# Cursor beforeShellExecution guard. Only runs for commands matching the matcher in .cursor/hooks.json.
# Hardware and serial commands: ask the human. Destructive git/file commands: deny.
input="$(cat)"

if echo "$input" | grep -Eq 'push .*(-f|--force)|rm -rf|reset --hard'; then
  echo '{"permission":"deny","user_message":"Blocked a destructive command (force push, rm -rf or reset --hard).","agent_message":"This command is blocked by project policy. Propose a safer alternative to the human instead."}'
  exit 0
fi

echo '{"permission":"ask","user_message":"This command may touch real hardware (serial port, motors or the EEG board). Approve only if you are holding the kill switch and the wheels are off the ground.","agent_message":"Agents must not run hardware commands. Stop and ask the human to run it."}'
exit 0
