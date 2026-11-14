# firmware/

**Owner:** Pratosh and Keshav

**Purpose:** Everything that runs below the laptop: the ESP32 safety bridge sketch, and the notes for flashing and
wiring the hoverboard mainboard.

| In | Out |
| --- | --- |
| Command lines from `motors/driver.py` over USB serial; ultrasonic echo | 8-byte speed frames to the hoverboard over 3.3 V UART; distance and status lines back to the laptop |

## Planned files (created during the hackathon, not before)
- `bridge/bridge.ino` - ESP32 sketch: line parser, 200 ms watchdog, ultrasonic read, local obstacle stop, clamp, hoverboard frame encoder
- `README.md` (this file, filled in on Friday) - photos of the mainboard, the multimeter-verified pin map for SWD, USART TX/RX, ground, and the higher-voltage sideboard line to avoid; which firmware version and build options were flashed

## Done when
Unplugging the laptop stops the wheels within 200 ms, a hand in front of the ultrasonic sensor stops forward motion, and the pin map is written here before anything is connected.

Humans compile and upload. Agents only write and review the sketch. Rules: `.cursor/rules/50-motors.mdc`, `AGENTS.md`. Contracts: `docs/INTERFACES.md`.
