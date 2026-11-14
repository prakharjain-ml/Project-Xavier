# motors/

**Owner:** Pratosh

**Purpose:** Send MotorCommands from the laptop to the ESP32 safety bridge, and report obstacles back to control.

| In | Out |
| --- | --- |
| `MotorCommand`, bridge status lines | Bridge command lines every 50 ms; `distance_cm` to control |

## Planned files (created during the hackathon, not before)
- bridge_protocol.py - encode command lines and parse status lines (docs/INTERFACES.md)
- driver.py - 20 Hz writer thread, sends S when stopped, reads distance/status (`-1` = out of range), clamps speed
- mock_serial.py - fake port for tests
- teleop.py - HUMAN ONLY keyboard drive, space = stop
- tests/ - line encoding and parsing, clamp, forward obstacle distance handling

## Done when
Mock tests pass; human-run wheels-off-ground spin at minimum speed.

Rules: `.cursor/rules/` (auto-attached for this folder) and `AGENTS.md`. Contracts: `docs/INTERFACES.md`.
