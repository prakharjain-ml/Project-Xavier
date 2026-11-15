# Interfaces (the contracts)

At kickoff an agent turns this file into `shared/protocol.py` (frozen dataclasses + enums + constants).
After that, change this file first, then regenerate. Everything marked VERIFY needs a real-hardware check.

> **Implementation status (Sat Nov 14).** Formats and rules below are unchanged. Known differences from the code:
> - Battery is 7S (about 28 V), frames are 9 bytes, firmware is RoboDurden's (not EFeru): already stated in the
>   hoverboard section below. Any 36 V, 8-byte or EFeru wording elsewhere (plan, `docs/GLOSSARY.md`, `docs/QUESTIONS.md`,
>   `docs/MESSAGES.md`) is out of date. Truth: `firmware/README.md`, `motors/bridge_protocol.py`.
> - The `# <text>` info lines and the bridge's TX/RX auto-detect are described by the debug log as running on the
>   boards. The sketch in the repo (`firmware/bridge/bridge.ino`) sends no `#` lines and has no auto-detect
>   (`firmware/hoverboard/DEBUG_LOG.md`, `PROGRESS.md`).
> - `D,` state `ESTOP` is listed but the repo sketch reports only `OK`, `OBSTACLE` and `WATCHDOG`.
> - `TargetSet` and `GoalHint` over UDP are defined in `shared/protocol.py` but nothing sends or receives them.
>   `vision/object_select.py --drive` calls the planner and state machine directly and owns the motor driver.
> - `StopRequest` sources ALPHA is never produced (no alpha detector). `Intent` comes from gaze or keyboard, not
>   an SSVEP decoder. `TARGET_FREQS_HZ`, `WINDOW_S`, `STEP_S`, `CONF_THRESHOLD`, `BANDPASS_HZ`, `ALPHA_BAND_HZ` apply
>   only to the unbuilt decoder.
> - The `GazeSample` message (eye tracker to app, UDP on 127.0.0.1) is not listed here; its format is
>   `vision/gaze.py` `encode_gaze_message()`.
> - Sampling rate: the dongle gives 250 Hz, the Wi-Fi shield about 1000 Hz (`docs/JAW_CONFIRM.md`). Read it from BrainFlow.
> Evidence: `docs/PROJECT_CONTEXT.md` sections 5 and 9.

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
| `MAX_SPEED` | 300 | firmware units (out of +-1000); raised from 150 on Sun Nov 15 at Prakhar's request |
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

### GoalHint (vision -> control; Mode 2) - added Sat Nov 14 ~3 am, confirm at 11 am sync
Where the chosen target is, so control can steer. Vision never sends wheel speeds; only `control/` turns this
into a `MotorCommand` (using `MAX_SPEED` / `TURN_SPEED`) and only while the state machine allows motion.
| Field | Type | Meaning |
| --- | --- | --- |
| `target_id` | int | track id from the TargetSet (negative = Gemini-only target such as a door) |
| `offset` | float -1..1 | horizontal position of the target: -1 far left, 0 straight ahead, +1 far right |
| `distance_m` | float or None | estimate from box size (not LiDAR, not a safety signal); None if unknown |
| `t` | float | monotonic time of the camera frame |
Rules: target lost or GoalHint older than `STALE_INTENT_S` -> control treats it as NONE -> STOP.

### Transport between processes (Mode 2, decision D3)
Vision runs as its own process and sends JSON over localhost UDP. Every message carries `"v": PROTOCOL_VERSION`
and `"type": "TargetSet" | "GoalHint"`. A message with a wrong version, unknown type or missing field is dropped
and logged; it is never partially used.

## Laptop to ESP32 bridge (USB serial, 115200 baud, newline-terminated ASCII)
Laptop to bridge, sent every 50 ms by `motors/driver.py`, even when stopped:
- `C,<seq>,<left>,<right>\n`: wheel speeds in firmware units, already clamped; `seq` counts up from 0
- `S,<seq>\n`: explicit stop
Bridge to laptop, sent every 50 ms:
- `# <text>\n`: human-readable info lines (e.g. `# LEFT board OK, RIGHT board NOT FOUND`, from the bridge's
  automatic TX/RX detection). Laptop parsers MUST ignore any line starting with `#` (added Sat Nov 14, Keshav).
- `D,<distance_cm>,<state>\n`: `distance_cm` is a positive int (`-1` when out of range / echo timeout, never `0` for timeout); `state` is `OK`, `OBSTACLE`, `WATCHDOG` or `ESTOP`
Bridge rules (enforced on the ESP32, not trusted to the laptop):
- No valid laptop line for `BRIDGE_WATCHDOG_MS` means speed zero until lines resume.
- Valid distance (`> 0` and `< OBSTACLE_STOP_CM`) while net forward speed `(left + right) > 0` means speed zero. In-place turns (`(-w, +w)` where `left + right == 0`) and reverse (`(left + right) < 0`) remain allowed so the rider is never trapped facing an obstacle.
- Use a short echo timeout (~20 ms, ~340 cm max) on HC-SR04 so `pulseIn` never stalls the 200 ms watchdog loop, and map echo timeout (`0` us) to `distance_cm = -1` (clear/out-of-range), never `0 cm`.
- Speeds are clamped again to `MAX_SPEED`. Malformed lines set speed to zero immediately.

## ESP32 to hoverboard firmware (UART) - verified against Keshav's flashed firmware, Sat Nov 14
Battery: **7S Li-ion (~28 V)**, not the 36 V assumed in the plan (`BAT_CELLS=7`). The link to each board is its
**5-pin master-slave plug** (P2 = board TX, P3 = board RX, P5 = ~14 V never connect); ESP32 GND must go to a
SOLID ground (SWD GND hole or the thick black battery wire), not P1. Details: `firmware/hoverboard/DEBUG_LOG.md`.
Board: YK187 master, GD32E235, RoboDurden Gen2.x-GD32 firmware (details: `firmware/README.md`).
- 19200 baud, 8N1, 3.3 V logic, on each board's 5-pin plug (PA2 = TX on P2, PA3 = RX on P3). Never connect a 5 V TX pin, and never touch the
  sideboard's higher-voltage line
- Command frame, 9 bytes, little-endian, packed: `uint8 '/'`, `int16 speed`, `int16 steer`, `uint8 wStateMaster`,
  `uint8 wStateSlave`, `uint16 crc` (CRC16-CCITT, poly 0x1021, init 0, over the first 7 bytes), with
  speed = (left + right) / 2 and steer = (right - left) / 2, both -1000..1000.
  Known-good example: speed=100, steer=0 -> `2F 64 00 00 00 00 00 A6 BD` (CRC re-checked in Python)
- The board sets speed 0 by itself after 500 ms without a valid frame (`LOST_CONNECTION_STOP_MILLIS`); the ESP32's
  own 200 ms watchdog is still the one we rely on. Wheel signs: VERIFY wheels-up.

## BrainFlow facts the code relies on
- `BoardShim(board_id, params)`, `prepare_session()`, `start_stream()`, `get_current_board_data(n)`,
  `stop_stream()`, `release_session()`
- Channels and rate from `BoardShim.get_eeg_channels(board_id)` and `BoardShim.get_sampling_rate(board_id)`
- MEASURED Sat Nov 14: our board streams at ~1000 Hz, not the 250 Hz assumed in the plan (36,192 rows in ~36 s of steady
  timestamps). Never hard-code 250: always read the rate from BrainFlow.
- Synthetic board for development; Cyton serial port is the dongle (`/dev/cu.usbserial-*`), VERIFY
