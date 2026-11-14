# Interfaces (the contracts)

At kickoff an agent turns this file into `shared/protocol.py` (frozen dataclasses + enums + constants).
After that, change this file first, then regenerate. Everything marked VERIFY needs a real-hardware check.

## Constants (single source)
| Name | Value | Notes |
| --- | --- | --- |
| `DISPLAY_HZ` | 60 | measure on the demo laptop |
| `TARGET_FREQS_HZ` | {FWD: 60/9, LEFT: 60/7, RIGHT: 12.0, BACK: 15.0} | locked starting set (D2), about 6.67, 8.57, 12 and 15 Hz; 9, 7, 5 and 4 frames per cycle; may change after Phase 3 calibration |
| `WINDOW_S` / `STEP_S` | 1.5 / 0.25 | decoder window and hop |
| `CONF_THRESHOLD` | 0.15 | kickoff default for fake-data tests; replaced from Phase 3 calibration |
| `DWELL_S` | 1.5 | hold time to select |
| `STALE_INTENT_S` | 0.5 | no fresh Intent -> STOP |
| `CONTROL_HZ` | 20 | control loop rate |
| `BRIDGE_WATCHDOG_MS` | 200 | ESP32 commands zero if no laptop line arrives within this |
| `BANDPASS_HZ` | (5, 40) | must clear 2 x 15 Hz = 30 Hz |
| `ALPHA_BAND_HZ` | (8, 13) | eyes-closed detector band (`bci/alpha.py`) |
| `MAX_SPEED` | 150 | kickoff default in firmware units (out of +-1000); VERIFY and tune in Phase 4 |
| `TURN_SPEED` | 120 | kickoff default in-place turn speed in firmware units; VERIFY in Phase 4 |
| `OBSTACLE_STOP_CM` | 50 | kickoff default ultrasonic threshold in cm; VERIFY in Phase 4 |

## Messages
### Intent (bci -> control, interface)
| Field | Type | Meaning |
| --- | --- | --- |
| `target` | Target enum: FWD, BACK, LEFT, RIGHT, NONE (Mode 2: also object id) | winning target, NONE below threshold |
| `confidence` | float 0-1 | margin-based confidence |
| `scores` | dict[Target, float] | raw per-target scores, for logging and the UI |
| `t` | float | `time.monotonic()` at window end |

### StopRequest (bci/alpha -> control; operator key -> control)
| Field | Type | Meaning |
| --- | --- | --- |
| `source` | enum: ALPHA, OPERATOR, FAULT | why (`E_STOP` latch sources; obstacle distance is non-latching, see below) |
| `t` | float | monotonic time |

### MotorCommand (control -> motors)
| Field | Type | Meaning |
| --- | --- | --- |
| `left` | int | wheel speed, clamped to +-MAX_SPEED |
| `right` | int | wheel speed, clamped |
| `stop` | bool | True means both zero, overrides left/right |
| `t` | float | monotonic time |

Target mapping (provisional): FWD -> (`MAX_SPEED`, `MAX_SPEED`); BACK -> (`-MAX_SPEED // 2`, `-MAX_SPEED // 2`); LEFT -> (`-TURN_SPEED`, `TURN_SPEED`); RIGHT -> (`TURN_SPEED`, `-TURN_SPEED`).
If the firmware takes speed/steer instead of left/right: speed = (left + right) / 2, steer = (right - left) / 2.

### ControlStatus (control -> interface)
| Field | Type | Meaning |
| --- | --- | --- |
| `state` | enum from SAFETY.md | current state |
| `held_target` | Target | target being dwelled on or moved (`NONE` when stopped) |
| `dwell_fraction` | float 0-1 | for the dwell bar |
| `confidence` | float 0-1 | latest decoder confidence (0.0 if stale) |
| `scores` | dict[Target, float] | latest per-target scores for UI debug overlay |
| `distance_cm` | int or None | latest ultrasonic distance (`None` if unknown/out of range) |

### TargetSet (vision -> interface, control; Mode 2)
List of up to 4: `id` (int, stable track id), `label` (str), `bbox` (x1, y1, x2, y2 px), `freq_hz` (assigned).

## Laptop to ESP32 bridge (USB serial, 115200 baud, newline-terminated ASCII)
Laptop to bridge, sent every 50 ms by `motors/driver.py`, even when stopped:
- `C,<seq>,<left>,<right>\n`: wheel speeds in firmware units, already clamped; `seq` counts up from 0
- `S,<seq>\n`: explicit stop
Bridge to laptop, sent every 50 ms:
- `D,<distance_cm>,<state>\n`: `distance_cm` is a positive int (`-1` when out of range / echo timeout, never `0` for timeout); `state` is `OK`, `OBSTACLE`, `WATCHDOG` or `ESTOP`
Bridge rules (enforced on the ESP32, not trusted to the laptop):
- No valid laptop line for `BRIDGE_WATCHDOG_MS` means speed zero until lines resume.
- Valid distance (`> 0` and `< OBSTACLE_STOP_CM`) while net forward speed `(left + right) > 0` means speed zero. In-place turns (`(-w, +w)` where `left + right == 0`) and reverse (`(left + right) < 0`) remain allowed so the rider is never trapped facing an obstacle.
- Use a short echo timeout (~20 ms, ~340 cm max) on HC-SR04 so `pulseIn` never stalls the 200 ms watchdog loop, and map echo timeout (`0` us) to `distance_cm = -1` (clear/out-of-range), never `0 cm`.
- Speeds are clamped again to `MAX_SPEED`. Malformed lines set speed to zero immediately.

## ESP32 to hoverboard firmware (UART, VERIFY against the flashed firmware)
Provisional, assuming the open-source hoverboard FOC firmware's USART command input:
- 115200 baud, 8N1, 3.3 V logic. Never connect a 5 V TX pin, and never touch the sideboard's higher-voltage line
- Frame: `uint16 start = 0xABCD`, `int16 steer`, `int16 speed`, `uint16 checksum = start ^ steer ^ speed`,
  little-endian, 8 bytes, with speed = (left + right) / 2 and steer = (right - left) / 2
- Sent every 20 to 50 ms. The firmware probably has its own serial timeout: VERIFY, but never rely on it

## BrainFlow facts the code relies on
- `BoardShim(board_id, params)`, `prepare_session()`, `start_stream()`, `get_current_board_data(n)`,
  `stop_stream()`, `release_session()`
- Channels and rate from `BoardShim.get_eeg_channels(board_id)` and `BoardShim.get_sampling_rate(board_id)`
- Synthetic board for development; Cyton serial port is the dongle (`/dev/cu.usbserial-*`), VERIFY
