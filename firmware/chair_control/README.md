# chair_control: drive the hoverboard wheelchair from Python

Location in the team repo: `firmware/chair_control/` (owners: Pratosh and Keshav). It speaks the laptop-to-bridge
protocol of `docs/INTERFACES.md`, the same one the planned `motors/driver.py` uses. Only one of them may hold the port.

`chair.py` is a small Python library that drives the SSVEP wheelchair's two hub motors through the
ESP32 bridge. It gives you `forward`, `backward`, `turn_left`, `turn_right`, `drive` and `stop`,
each with a speed parameter, and handles keep-alive, speed limits, smooth acceleration and safe shutdown.

```python
from chair import Chair                 # when your script is inside chair_control/
# from firmware.chair_control import Chair   # when your script runs from the repo root

with Chair("COM4") as chair:
    chair.forward(200, 2)               # speed 200 for 2 s, then stop
    chair.turn_left(150, 1)             # spin left in place for 1 s
    chair.backward(200, 2)
    chair.turn_right(150, 1)
# leaving the with-block always stops the chair and frees the COM port
```

Files in this folder:

| File | Purpose |
|---|---|
| `chair.py` | The library (class `Chair`). Fully commented. |
| `__init__.py` | Makes the folder a package: `from firmware.chair_control import Chair` from the repo root. |
| `example.py` | First drive test: `python firmware/chair_control/example.py COM4`. |
| `README.md` | This document. |

---

## 1. System overview

```
Python (this library, laptop)
   |  USB serial, 115200 baud, text lines, every 50 ms
   v
ESP32-S3 bridge  (sketch: bridge/bridge.ino)
   |  watchdog 200 ms, obstacle stop (HC-SR04), speed clamp MAX_SPEED, flips the mirrored right motor
   |  two UARTs at 19200 baud, binary hoverboard protocol
   v
LEFT board (master, GD32E235)          RIGHT board (slave, GD32E235)
RoboDurden Gen2 firmware, option 5     RoboDurden Gen2 firmware, option 5
   |                                       |
   left hub motor                          right hub motor
```

- The laptop **never** talks to the hoverboard boards directly. It only talks to the ESP32.
- The ESP32 must be plugged into the laptop by USB. That cable is both its power and its data.
  A power bank alone is not enough: nothing would send commands.
- The Arduino IDE does **not** need to be running. The ESP32 keeps its program when powered off.
  **Close the Arduino Serial Monitor** before using this library: only one program can open the COM port at a time.

---

## 2. Installation

```bash
pip install pyserial
```

Python 3.8+. No other dependencies. Find the port: Windows Device Manager → Ports (the ESP32-S3 shows as
"USB Serial Device", usually `COM4` on Keshav's laptop). On macOS it is `/dev/cu.usbmodem…`, on Linux `/dev/ttyACM0`.

---

## 3. API reference

### `Chair(port="COM4", max_speed=850, accel=60, verbose=True)`
Opens the bridge and starts two background threads (sender and reader).
Waits about 2 s, because the ESP32 may reboot when the port opens and needs time to find both boards.

| Parameter | Meaning |
|---|---|
| `port` | Serial port of the ESP32. |
| `max_speed` | Hard cap for every command, 0..1000. Higher requests are **clamped** (not refused). Default **850**. |
| `accel` | Maximum speed change per 50 ms tick. 60 means 0 → 850 takes about 0.7 s. `0` or `None` = instant changes. |
| `verbose` | Print bridge info lines (`board found` / `board lost`) and obstacle warnings. |

Create **one** `Chair` per program. Use it as a context manager (`with Chair(...) as chair:`) or call `chair.close()`.
It is also closed automatically at program exit (`atexit`).

### Moves

| Method | Wheels | Notes |
|---|---|---|
| `forward(speed, seconds=None)` | both forward | `speed` sign is ignored (always forward). |
| `backward(speed, seconds=None)` | both backward | |
| `turn_left(speed, seconds=None)` | left back, right forward | Spins in place, counter-clockwise seen from above. |
| `turn_right(speed, seconds=None)` | left forward, right back | Spins in place, clockwise seen from above. |
| `drive(left, right, seconds=None)` | each wheel separately | -max..+max, positive = forward. Different values = curve. |
| `stop()` | both 0 | Immediate, no ramp. Safe to call any time. |
| `close()` | stops, frees the port | Idempotent. |

**The `seconds` argument:**
- `seconds=2`: the call **blocks** for 2 s (ramp-up time included), then stops the chair. Ctrl+C during the wait also stops.
- `seconds=None` (default): the call returns **immediately** and the chair **keeps moving** until the next command
  or `stop()`. Use this in control loops (SSVEP classifier, object following):

```python
with Chair("COM4") as chair:
    while running:
        cmd = classifier.latest()           # your code
        if cmd == "forward":  chair.forward(250)
        elif cmd == "left":   chair.turn_left(150)
        elif cmd == "right":  chair.turn_right(150)
        else:                 chair.stop()
        time.sleep(0.1)
```

Calling a move repeatedly with the same value is fine and cheap: it only changes the target.
The background thread does the sending.

### Status (read-only attributes, updated about 20× per second)

| Attribute | Values |
|---|---|
| `chair.state` | `"OK"`, `"OBSTACLE"` (bridge is blocking forward motion), `"WATCHDOG"` (bridge got no commands for >200 ms, wheels stopped), `"?"` (nothing received yet) |
| `chair.distance_cm` | Ultrasonic distance in cm; `0` = no echo or no sensor connected |

---

## 4. Speed: units and limits

- **Unit:** hoverboard firmware PWM units, **-1000..+1000**. 1000 = 100 % motor power. It is **power, not km/h**:
  the same number goes slower uphill, with a heavier rider or with a lower battery.
- **Dead zone:** |speed| below about **50** does nothing (firmware threshold).
- **Rough feel** (wheels in the air, 7S battery about 27–29 V): 1000 is around 10 km/h unloaded. Slower with a rider.
  The team will measure real values; update this line when you do.
- **Suggested starting values:** 150–250 for testing, 150 for spinning in place.

Three limits apply, and the lowest one wins:

| Where | Value | Change it |
|---|---|---|
| `Chair(max_speed=…)` in this library | **850** default | Constructor argument, or `DEFAULT_MAX_SPEED` in `chair.py` |
| `MAX_SPEED` in `bridge/bridge.ino` (ESP32) | 910 at time of writing | Edit, then re-upload with the Arduino IDE |
| Firmware | ±1000, plus a 15 A motor current limit | Not needed |

Full power does not damage the motors: hoverboard motors are made to carry a person at full power,
and the firmware limits the current to 15 A. The 850 cap is for the **rider's** safety.

---

## 5. Safety behaviour (what happens when things go wrong)

| Event | Result |
|---|---|
| Your script ends, crashes, freezes, or the USB cable is pulled | No more commands → ESP32 stops the wheels after **200 ms** (`WATCHDOG`). The boards also stop by themselves after 500 ms without data from the ESP32. |
| Ctrl+C during a timed move | `stop()` runs immediately. |
| Leaving `with Chair(...)` or program exit | `close()` sends stop several times. |
| Ultrasonic sensor < 50 cm and the command is net forward | ESP32 forces speed 0 (`OBSTACLE`). Backward and spinning still work so you can get away. |
| Battery low | The firmware beeps. Charge it. |
| **Emergency (hardware)** | **Pull the kill key**: the Dupont jumper on the two wires coming out of the shell. That cuts board power at once. |

The kill key replaces the original power button. **Key in = boards on, key out = boards off.**
Pull it whenever the chair is parked: the boards otherwise stay on and slowly drain the battery.

Speed changes are ramped (`accel`) so the rider is not jerked. `stop()` is **not** ramped;
the firmware brakes softly over about 1 s by itself.

---

## 6. Serial protocol (laptop ↔ ESP32)

The library implements this; it is documented here for anyone writing another client. Source of truth:
the team repo's `docs/INTERFACES.md`.

Laptop → ESP32, 115200 baud, one line per 50 ms (must keep sending, or the watchdog stops the chair):
```
C,<seq>,<left>,<right>\n     drive; left/right = -1000..1000, positive = forward
S,<seq>\n                    stop
```
`<seq>` is an increasing integer (for debugging only).

ESP32 → laptop:
```
D,<distance_cm>,<state>\n    every 50 ms; state = OK | OBSTACLE | WATCHDOG
# <text>\n                   info messages (board found/lost, battery voltage). Parsers must ignore them.
```

---

## 7. Notes for AI agents (Claude Code etc.)

- **Do not run this against the real chair yourself.** A human with the kill key in reach runs anything that
  moves the wheels (team rule in `AGENTS.md`: agents never open serial ports or upload firmware).
  You may write and edit code, and test it against a fake port (see below).
- **Testing without hardware:** monkeypatch `serial.serial_for_url` to return a fake object with
  `write`, `readline` (return e.g. `b"D,0,OK\n"`), `reset_input_buffer` and `close`, then inspect the written
  lines. `serial_for_url` also accepts `"loop://"`.
- **Do not add a second sender** to the same port. One `Chair` object per process.
- **Keep the keep-alive.** Anything that blocks the sender thread for more than about 150 ms makes the chair stop
  (`WATCHDOG`). That is by design.
- **Wheel direction and left/right mapping are handled in `bridge.ino`** (`LEFT_SIGN` / `RIGHT_SIGN`,
  currently `1` / `-1`). Never compensate for them in Python.
- **Units are firmware units, not m/s.** Do not convert unless odometry has been added (see roadmap).
- When adding features, keep `forward/backward/turn_left/turn_right/drive/stop` backward compatible:
  other team code imports them.

---

## 8. Troubleshooting

| Symptom | Fix |
|---|---|
| `WARNING: no status from the ESP32 bridge` | Wrong COM port, or the Arduino Serial Monitor / another script has the port. Close it, re-plug USB. |
| `could not open port … Access is denied` | Another program has the port (Serial Monitor, a second script). |
| `[bridge] LEFT board NOT FOUND` (or RIGHT) | Board not powered (kill key in?), or a data or ground wire is loose inside the shell. |
| `state` stays `WATCHDOG` | Commands are not arriving: a blocked script, or the port was closed. |
| `state` is `OBSTACLE` and forward does nothing | Something within 50 cm of the ultrasonic sensor. Back up or spin. |
| A wheel turns the wrong way | Change `LEFT_SIGN`/`RIGHT_SIGN` in `bridge/bridge.ino`, re-upload. Not in Python. |
| Left and right are swapped (turn_left turns right) | Swap the ESP32 wire pairs (GPIO17/18 ↔ GPIO15/16), or swap the pin defines in `bridge.ino`. |
| Wheels twitch but don't turn at low speed | Below the dead zone (~50) or not enough torque under load; use a higher speed. |
| One wheel dead after the chair stood still a long time | Should not happen with firmware option 5 (no auto power-off). If it does, pull and re-insert the kill key. |

---

## 9. Hardware reference (for maintainers)

- **ESP32 wiring** (all in `bridge.ino`): left board TX/RX on GPIO17/18, right board on GPIO15/16. The bridge
  auto-detects which of the two is TX. One ESP32 GND to each board's **SWD GND hole**, never to plug pin P1
  (60 Hz hum). Each board's 5-pin master-slave plug: P2 = board TX (PA2), P3 = board RX (PA3), P5 = about 14 V
  (never connect it to the ESP32). The original 5-pin cable between the boards is removed.
- **Firmware:** RoboDurden Hoverboard-Firmware-Hack-Gen2.x-GD32, GD32E230 build (TARGET 3, layout 2-3-9),
  REMOTE_UART on USART1 at 19200 baud, `e235_single_usart1_hold.bin` ("option 5" in
  `flash_tools/7_flash_firmware.bat`) on both boards: no button handling, no inactivity power-off.
- **Power:** the chip cannot hold its own power (every free pin was tested), so the power button was replaced by
  the kill-key jumper.

---

## 10. Roadmap

- **Drive by distance and turn by degrees** (`forward_m(speed, meters)`, `turn_left_deg(speed, deg)`):
  the boards already send wheel odometry (hall-step counters) to the ESP32 10× per second. Next step: the ESP32
  forwards it to the laptop (for example a new line `O,<left_steps>,<right_steps>`, added to
  `docs/INTERFACES.md`), and this library converts steps to meters with the wheel circumference.
- Measure real speeds (km/h per speed unit with a rider) and put them in section 4.
