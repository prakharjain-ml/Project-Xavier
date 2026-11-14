# Project context and independent audit

Written Sat Nov 14, 2026 (evening) by an independent auditing agent. It describes commit `1711282` on branch
`prakhar/gaze`. Other agents were editing the route preview at the same time (`vision/hud.py`,
`vision/nav_preview.py`, `vision/floor_route.py`, `vision/scene_ai.py`, `vision/detect_track.py`,
`control/astar.py`), so for those files this document describes the committed version only.

How to read the labels in this document:

| Label | Meaning |
| --- | --- |
| PROVEN | I ran the project's own code and saw it happen. Nothing here was run on hardware: cameras, the headset, the serial port and the motors were always replaced by fakes. |
| LIKELY | Read from the code or the repo's own notes, not run. |
| QUESTION | I could not tell. The team has to answer. |
| "per PROGRESS.md" and similar | A claim I found in the repo and did not re-check. |

Every number below is either a constant in the code, a figure quoted from a named file in the repo, or the
output of a command I ran. I ran no hardware and read no secrets.

---

## 1. What it is and who it is for

A team of four at HackPrinceton Fall 2026 (hacking ends Sunday Nov 15, 8:00 am; Healthcare track) is building a
wheelchair for a person who cannot use a joystick, for example after a high spinal cord injury or with ALS.

What the rider does today:

1. Sits in front of a laptop. A webcam watches their eyes (gaze tracking).
2. A second camera looks forward. The laptop draws a box on each object it recognises (chairs, tables, people).
3. The rider looks at a box. They confirm the choice by holding their gaze for 1.5 s (dwell), or by clenching
   their jaw, which an OpenBCI headset picks up as a muscle signal.
4. While the rider keeps looking at the confirmed object, the chair drives toward it. Looking away stops it.

A simpler mode shows four arrows (forward, back, left, right) instead of objects and works the same way.

History that explains the names in the repo: the original plan was to steer with brain signals. Four arrows
would flicker at different rates and the headset would detect which one the rider stared at. That effect is
called SSVEP (steady-state visually evoked potential). The first recording had no usable signal (per
PROGRESS.md: no 15 Hz peak, signal-to-noise about 1), so on Saturday the team switched to gaze plus jaw clench.
The repo, `AGENTS.md`, `README.md` and several docs still describe the SSVEP product.

The team: Keshav (hardware), Pratosh (motors and integration), Vani (vision and headset), Prakhar (screen,
safety logic, docs, demo).

Terms used below, defined once:

| Term | Meaning |
| --- | --- |
| Gaze | Where on the screen the rider is looking, as two numbers from 0 to 1 (left to right, top to bottom). |
| Dwell | Keeping the gaze on one thing for a set time (1.5 s) to select it. |
| Hold-to-move | The chair moves only while the rider keeps looking at the chosen thing. |
| EMG | The electrical buzz of a working muscle. A jaw clench is EMG, not a brain signal. |
| Bridge | The ESP32 microcontroller between the laptop and the hoverboard. |
| Watchdog | A timer that stops the wheels when the expected messages stop arriving. |
| State machine | `control/state_machine.py`: the single function that decides whether the wheels may move. |
| Planner | Code that turns "the object is there" into wheel speeds. There are two, see section 4.6. |
| Mock port | `motors/mock_serial.py`: a fake serial port used for every test, so no motor can move. |
| Firmware units | Wheel speed numbers sent to the hoverboard, from -1000 to 1000. The code caps them at 150. |

---

## 2. Hardware and how the pieces connect

```
 rider's eyes --> laptop camera -------> eye tracker program --(UDP, this laptop only)--+
                                                                                         v
 forward camera (Pixel phone as webcam) --> YOLO object detector ------------> vision/object_select.py
                                                                                         |
 jaw --> electrodes --> OpenBCI Cyton --(USB dongle or Wi-Fi)--> bci/jaw_live.py --------+
                                                                                         v
                                                              control/ planner + safety state machine
                                                                                         v
                                                                   motors/driver.py (20 lines per second)
                                                                                         | USB serial, text
                                                                                         v
        ultrasonic sensor ----------------------------------------> ESP32-S3 bridge (watchdog, obstacle stop)
                                                                                         | 2 x UART, 9-byte frames
                                                                                         v
                         battery --[kill switch]--> two hoverboard boards (one per wheel) --> two hub motors
```

| Part | What the repo says about it | Source | State |
| --- | --- | --- | --- |
| Laptop | MacBook Air M2, runs all Python | `AGENTS.md` | in use |
| Eye camera | The camera that sees the rider's face (built-in). Found automatically by looking for a face | `vision/camera_roles.py` | works live per PROGRESS.md |
| Forward camera | Pixel phone in webcam mode, 1920x1080, measured field of view 85.5 degrees | `data/raw/camera_calibration.json` | "FLAKY: Pixel drops webcam mode when it sleeps" (`docs/GAMEPLAN_SAT.md`) |
| Headset | OpenBCI Cyton. USB dongle gives 250 samples per second; the Wi-Fi shield gave about 1000 | `docs/JAW_CONFIRM.md`, `docs/INTERFACES.md` | last recording was pinned at the amplifier limit ("railed"); never produced a usable signal |
| Bridge | ESP32-S3 dev board, USB serial at 115200 baud | `firmware/bridge/bridge.ino` | left wheel driven through it per PROGRESS.md |
| Ultrasonic sensor | HC-SR04, TRIG on GPIO4, ECHO on GPIO5 through a 1k/2k divider | `firmware/README.md` | listed as a to-do in `docs/GAMEPLAN_SAT.md`; no test result anywhere in the repo |
| Hoverboard | Split board: two YK187 boards with GD32E235 chips, re-flashed with RoboDurden's open firmware (`e235_single_usart1.bin`), one board per wheel | `firmware/README.md` | LEFT wheel works end to end; RIGHT board still being unlocked (PROGRESS.md, Sat evening) |
| Board link | Each board's 5-pin plug: P2 = board TX, P3 = board RX, P5 is about 14 V and must never be connected. Ground must be a solid ground, not P1 | `firmware/hoverboard/DEBUG_LOG.md`, `docs/INTERFACES.md` | `firmware/README.md` and the sketch header still say "4-pin plug" (see finding 4) |
| Battery | 7 cells lithium-ion, 27.7 V measured (not the 36 V in the plan and `AGENTS.md`) | `firmware/README.md` | in use |
| Kill switch | Planned: latching button that cuts battery power to the boards | plan section 2 | listed as a to-do; no evidence it is fitted |
| Chassis | Plank, chair, casters | plan section 2 | listed as a to-do |

---

## 3. Folder by folder

| Path | What lives there | Notes |
| --- | --- | --- |
| `app.py` | Arrows mode. pygame screen + safety state machine + motor driver in one process. `--keyboard` or `--gaze`, `--mock` or `--serial PORT` | SPACE = operator emergency stop, R = re-arm |
| `shared/protocol.py` | Every shared message, enum and constant | A test checks the constants against `docs/INTERFACES.md` |
| `shared/latest.py` | Helpers for "keep only the newest item" queues | |
| `control/state_machine.py` | `step(prev, inputs, now, mapping)`: the safety state machine. Pure function, no clock, no I/O | 53 tests |
| `control/navigation.py` | Planner 1: Dynamic Window Approach (DWA), adapted from PythonRobotics. Picks speed and turn rate | this one produces wheel speeds |
| `control/goto.py` | `nav_step()`: one planner step per video frame, builds obstacles from camera boxes and the ultrasonic reading | |
| `control/astar.py` | Planner 2: A* shortest path on a 10 cm floor grid | drawing only, never drives |
| `motors/driver.py` | `MotorDriver`: background thread, writes one line to the bridge every 50 ms, reads distance lines back | never picks a port by itself |
| `motors/bridge_protocol.py` | Encode `C`/`S` lines, parse `D` lines | |
| `motors/mock_serial.py` | Fake serial port | |
| `bci/jaw.py`, `bci/jaw_live.py` | Jaw-clench detector and its live wrapper (`JawConfirmSource`) | the only code in `bci/` |
| `vision/gaze.py` | Gaze math, blink rule, hit-testing with hysteresis, the UDP message format | |
| `vision/gaze_tracker.py`, `vision/gaze_tracker_eyetrax.py` | Two eye tracker programs (MediaPipe-based built-in one, and EyeTrax in its own virtual environment). EyeTrax is the default when `~/venvs/eyetrax` exists (it does on this laptop) | each runs as its own process |
| `vision/gaze_link.py` | Starts the tracker process and receives its UDP messages | |
| `vision/gaze_calibrate.py` | 9-dot calibration and accuracy check for the built-in tracker | |
| `vision/camera_source.py`, `camera_roles.py`, `camera_view.py` | Camera reader thread (newest frame only), which-camera-is-which, a viewer | |
| `vision/detect_track.py` | YOLO11n + ByteTrack, distance from box height, target ranking | |
| `vision/destinations.py` | Optional Gemini ranking of destinations for `detect_track --gemini` | not used by `object_select` at this commit |
| `vision/object_select.py` | Object mode: gaze on boxes, confirm, and with `--drive` the whole drive loop | the current demo path |
| `vision/nav_preview.py`, `hud.py`, `floor.py` | Route preview screen. Sends nothing to motors | being rebuilt, see section 10 |
| `interface/flicker.py`, `timing.py` | The pygame arrow screen (flickering for SSVEP, static for gaze) | |
| `firmware/bridge/bridge.ino` | ESP32 sketch | not the sketch that is on the ESP32, see finding 4 |
| `firmware/hoverboard/` | Flash tools, prebuilt board firmware, pin notes, bring-up log, a human-only bench test | excluded from pytest on purpose |
| `tools/` | Only a README | `tools/smoke.py`, named in `AGENTS.md` as the check before every merge, does not exist |
| `docs/` | Contracts (`INTERFACES.md`), safety spec (`SAFETY.md`), plans, Devpost draft | several are stale, see section 9 |
| `data/raw/` | Git-ignored: one EEG recording, gaze and camera calibration | |

Planned files that do not exist on any local branch: `bci/acquire.py`, `filters.py`, `ssvep.py`, `decoder.py`,
`alpha.py`, `control/mapping.py`, `motors/teleop.py`, `vision/servo.py`, `tools/smoke.py`. So there is no SSVEP
decoder and no closed-eyes detector in the repo: only the flicker screen was built. All working code is on
`prakhar/gaze`; local `main` has only README files in `bci/`, `control/`, `motors/` and `tools/`.

---

## 4. From the rider's eyes to the wheels (object mode, `python -m vision.object_select --drive ...`)

### 4.1 Start-up (`vision/object_select.py` `main`)
1. `probe_cameras()` and `assign_roles()` decide which camera sees a face (eye camera) and which does not
   (forward camera).
2. Gaze calibration in the rider's current seat: `calibrate_eyetrax()` or `calibrate_now()`.
3. `LatestFrameReader.start()` begins reading the forward camera on a thread.
4. `start_gaze_tracker()` launches the eye tracker as a separate program.
5. With `--drive`: `MotorDriver.start()`. From now on a STOP line goes to the port every 50 ms.
6. With `--confirm jaw`: `start_jaw()` connects the headset, runs a guided calibration (10 s relaxed, 3
   clenches) and starts the detector thread.
7. `run()` is the main loop. Everything below happens once per pass of that loop.

### 4.2 Eyes to gaze point
| Step | File and function | What happens |
| --- | --- | --- |
| Camera frame to gaze | `vision/gaze_tracker_eyetrax.py` `stream()` or `vision/gaze_tracker.py` `run_gaze_process()` | One gaze point per camera frame |
| Blink rule | `vision/gaze.py` `update_blink()` | Eyes closed up to 0.4 s keep the last point. Longer, or no face, gives "no gaze" |
| Send | `vision/gaze.py` `encode_gaze_message()` | JSON over UDP to `127.0.0.1` on a port chosen at start |
| Receive | `vision/gaze_link.py` `start_gaze_tracker()` inner `receive()` | `decode_gaze_message()` drops anything malformed and stamps the sample with the receiver's clock on arrival |
| Freshness | `vision/object_select.py` `corrected_point()` | A sample older than 0.5 s counts as no gaze. C key re-centres |

### 4.3 Forward camera to boxes
| Step | File and function | What happens |
| --- | --- | --- |
| Newest frame | `vision/camera_source.py` `LatestFrameReader.latest()` | Returns the last frame it has, however old (see finding 1) |
| Detect and track | `vision/detect_track.py` `detect()` | YOLO11n + ByteTrack, 16 indoor classes, confidence at least 0.4 |
| Distance | `estimate_distance_m()` | typical height of that kind of object x focal length / box height in pixels |
| Choose what to show | `pick_targets()` then `separate_targets()` | Longest-seen first; at most 4; a box closer than 5% of the frame width to a better-ranked box is dropped |

### 4.4 Gaze to a confirmed object
| Step | File and function | What happens |
| --- | --- | --- |
| Which box | `hit_boxes()` and `vision/gaze.py` `pick_region()` | Small boxes are enlarged to 12% of the screen. Enter a box when 2% inside it, leave when 8% outside |
| Confirm | `update_selection()` | Dwell mode: 1.5 s on the same box. Key mode: J. Jaw mode: a clench. Key and jaw need 0.3 s of looking first |
| Jaw path | `bci/jaw_live.py` `JawConfirmSource._run()`, `JawStream.push()`, `bci/jaw.py` `emg_rms()`, `update_jaw()` | Every 0.1 s: energy between 40 and 200 Hz, skipping 12 Hz either side of 60/120/180 Hz. A clench counts after 0.3 s above the calibrated threshold, once per clench, at most one per second |

### 4.5 Confirmed object to a motor command (`drive_tick()`)
1. `control/goto.py` `nav_step()`: target position from its box (`goal_from_target()`), obstacles from the
   other shown boxes (`obstacles_from_tracks()`) and the ultrasonic reading, then
   `control/navigation.py` `dwa_control()` and `to_wheels()` give proposed (left, right) speeds. If the
   estimated distance is under 0.7 m (`ARRIVE_M`) it reports "arrived" and the confirmation is cleared.
2. `drive_intent()`: FORWARD only while the gaze is on the confirmed object and that object is still shown.
   Otherwise NONE.
3. `control/state_machine.py` `step()` with the planner's speeds as the mapping. The state machine alone
   decides whether those speeds are sent: it needs 1.5 s of unbroken FORWARD intent first, and it sends STOP
   the moment the intent is NONE or the ultrasonic reads under 50 cm.
4. `driver.send(command)`.

### 4.6 The two planners
| Planner | File | Used for | Drives the wheels? |
| --- | --- | --- | --- |
| Dynamic Window Approach | `control/navigation.py` | Tries speed and turn-rate pairs reachable in one step, simulates each 1.5 s ahead, drops any that pass within 0.45 m of an obstacle point, scores the rest | Yes, through `nav_step()` and the state machine |
| A* | `control/astar.py` | Shortest path on a floor grid for the preview screen | No. The route drawn on screen is not the route the chair takes |

### 4.7 Laptop to wheels
| Step | File and function | What happens |
| --- | --- | --- |
| Line writer | `motors/driver.py` `MotorDriver._run()` | Every 50 ms: newest command, or STOP if that command is older than 0.2 s. Reopens a lost port once per second |
| Bridge | `firmware/bridge/bridge.ino` `readLaptop()`, `parseLine()`, `loop()` | Parses lines, applies watchdog, obstacle rule and clamp, sends one frame per board every 50 ms, reports distance |
| Boards | RoboDurden firmware | Per `firmware/README.md`: sets speed 0 by itself 500 ms after the last valid frame |

### 4.8 Arrows mode (`app.py`)
Same chain with a pygame screen. `GazeIntentSource.snapshot()` or `KeyboardIntentSource.snapshot()` produce an
`Intent` 20 times a second, `control_tick()` calls `step()` with the fixed table in `provisional_mapping()`
(forward 150/150, back -75/-75, left -120/120, right 120/-120) and hands the command to the same driver.

---

## 5. Messages, serial formats and constants

### 5.1 Inside the Python process (`shared/protocol.py`, all frozen dataclasses)
| Message | From, to | Fields |
| --- | --- | --- |
| `Intent` | input source to state machine | `target` (FWD, BACK, LEFT, RIGHT, NONE), `confidence` 0 to 1, `scores`, `t` |
| `StopRequest` | operator key to state machine | `source` (ALPHA, OPERATOR, FAULT), `t`. Only OPERATOR is ever produced, and only by `app.py` |
| `MotorCommand` | state machine to driver | `left`, `right`, `stop`, `t` |
| `ControlStatus` | state machine to screen | `state`, `held_target`, `dwell_fraction`, `confidence`, `scores`, `distance_cm` |
| `TargetSet`, `TargetInfo`, `GoalHint` | defined for a vision process talking to control | defined and documented but nothing sends or receives them; `object_select` calls the planner and state machine directly |

### 5.2 Eye tracker to app (UDP on 127.0.0.1, one JSON object per datagram)
`{"v": 1, "type": "GazeSample", "x": 0.0-1.0 or null, "y": 0.0-1.0 or null, "closed": bool, "face": bool}`.
Wrong version, wrong type, missing field or wrong type of field: dropped whole. This message is not listed in
`docs/INTERFACES.md`.

### 5.3 Laptop to bridge (USB serial, 115200 baud, text lines)
| Direction | Line | Meaning |
| --- | --- | --- |
| laptop to bridge, every 50 ms | `C,<seq>,<left>,<right>\n` | wheel speeds, already clamped to 150 |
| laptop to bridge | `S,<seq>\n` | stop (also sent when both speeds are 0) |
| bridge to laptop, every 50 ms | `D,<distance_cm>,<state>\n` | distance is -1 when there is no echo; state is OK, OBSTACLE or WATCHDOG |
| bridge to laptop | `# text\n` | information lines, ignored by the laptop. Documented, but the sketch in the repo does not send them |

The sequence number is sent and parsed but never checked by the bridge.

### 5.4 Bridge to each hoverboard board (UART, 19200 baud, 8N1, 3.3 V)
9 bytes, little-endian: `'/'`, `int16 speed`, `int16 steer`, `uint8 0`, `uint8 0`, `uint16 CRC16-CCITT` (poly
0x1021, start 0, over the first 7 bytes). With one board per wheel, speed = that wheel's speed and steer = 0.
Example from the docs, reproduced by my host run of the sketch: speed 100 gives `2F 64 00 00 00 00 00 A6 BD`.

### 5.5 Constants that shape behaviour
| Constant | Value | Where |
| --- | --- | --- |
| `DWELL_S` | 1.5 s | `shared/protocol.py` |
| `STALE_INTENT_S` | 0.5 s | `shared/protocol.py` |
| `CONTROL_HZ` | 20 | `shared/protocol.py` |
| `MAX_SPEED` / `TURN_SPEED` | 150 / 120 firmware units | `shared/protocol.py`, also `#define MAX_SPEED 150` in the sketch |
| `OBSTACLE_STOP_CM` | 50 | `shared/protocol.py` and the sketch |
| `BRIDGE_WATCHDOG_MS` | 200 | `shared/protocol.py` and the sketch |
| `COMMAND_STALE_S` / `BRIDGE_STALE_S` / `REOPEN_S` | 0.2 / 0.5 / 1.0 s | `motors/driver.py` |
| `ARRIVE_M` | 0.7 m | `control/navigation.py` |
| Planner top speed, turn rate, radius, look-ahead | 0.4 m/s, 40 deg/s, 0.45 m, 1.5 s | `NavConfig` in `control/navigation.py` |
| `MIN_LOOK_S` | 0.3 s | `vision/object_select.py` |
| `BLINK_MAX_S` | 0.4 s | `vision/gaze.py` |
| Jaw window, hold, rest, ratio | 0.1 s, 0.3 s, 1.0 s, 3x | `bci/jaw.py` |
| Detection confidence, max targets, minimum gap | 0.4, 4, 5% of frame width | `vision/detect_track.py` |

Nothing ties the three `#define`s in the sketch to `shared/protocol.py`; they match today because someone typed
the same numbers.

---

## 6. The safety model and every way the chair stops

### 6.1 States (`control/state_machine.py`)
| State | Wheels | Leaves when |
| --- | --- | --- |
| `STOPPED` | stop | a confident target appears (and it is not FORWARD into an obstacle): go to `DWELLING` |
| `DWELLING` | stop | same target for 1.5 s: `MOVING`. Anything else: `STOPPED` |
| `MOVING` | mapped speeds, clamped | target changes, NONE, low confidence, stale intent, or FORWARD with obstacle under 50 cm: `STOPPED` |
| `E_STOP` | stop, latched | only an operator re-arm, and only if no stop request arrived in the last 0.5 s |

Any exception inside `step()` gives STOP. A stale or missing intent never clears `E_STOP`.

### 6.2 Every stop path
| # | What triggers it | Decided in | Latched? | Works in object drive mode? | Evidence |
| --- | --- | --- | --- | --- | --- |
| 1 | Gaze leaves the confirmed object or arrow | `drive_intent()` / `pick_region()` then `step()` | no; a new 1.5 s hold restarts motion | yes | tests on the mock port; never timed end to end |
| 2 | Eyes closed longer than 0.4 s, or face lost | tracker `update_blink()` | no | yes | tests |
| 3 | Eye tracker silent for 0.5 s | `corrected_point()` | no | yes | tests |
| 4 | Eye tracker process exits | `run()` `tracker_alive()` | ends the session | yes | test |
| 5 | Confirmed object no longer among the shown boxes | `drive_intent()` | no | yes | test |
| 6 | Planner reports arrival (estimate under 0.7 m) | `nav_step()` | clears the confirmation | only for short objects, see finding 2 | simulation |
| 7 | Ultrasonic under 50 cm while going forward, laptop side | `step()` `forward_blocked()` | no | yes, if the sensor works | tests with fake distances |
| 8 | Same, bridge side (net forward speed only; turns and reverse pass) | `bridge.ino` `loop()` | no | yes, if the sensor works | my host run of the sketch logic |
| 9 | X key | `run()` | no | key and jaw mode only; no effect in dwell mode, see finding 3 | PROVEN |
| 10 | Q or ESC, or the program ends | `main()` `finally`, `MotorDriver.stop()` | ends the session | yes | tests |
| 11 | Operator SPACE (emergency stop) and R (re-arm) | `app.py` `OperatorKeys` | yes | no: arrows mode only, see finding 3 | tests / PROVEN |
| 12 | Main loop hangs for more than 0.2 s | `MotorDriver._current_command()` | no | yes | tests, and section 8 finding 12 |
| 13 | Laptop silent for 200 ms | bridge watchdog | until lines resume | yes | host run of the sketch logic: zero frame 213 to 250 ms after the last line (the rule is checked every 50 ms); "watchdog stop verified" on the left wheel per PROGRESS.md |
| 14 | Malformed line | bridge `readLaptop()` | until the next valid line | yes | host run |
| 15 | Bridge dead or unpowered | board firmware, 500 ms | until frames resume | yes | `firmware/README.md`; not in my reach |
| 16 | Kill switch | hardware | yes | unknown | no evidence it is fitted |

Not implemented although the docs promise it: "closing the eyes puts it into latched `E_STOP`" (`docs/SAFETY.md`
layer 5, `docs/DEMO.md`). There is no closed-eyes detector. Closed eyes give stop path 2, which is not latched:
open the eyes on the object and the chair moves again after 1.5 s.

A consequence of the design worth knowing: in object mode the intent is always FORWARD, so inside 50 cm of an
obstacle the state machine blocks every command, including turning away. The "rider is never trapped" property
of the arrows mode does not carry over. The rider needs arrows mode or a helper to get out.

---

## 7. How to run things

Always first: `cd "/Users/prakharjain/HP Auto WheelChair" && source ~/venvs/hp26/bin/activate`

| Command | What it does | Hardware it touches |
| --- | --- | --- |
| `python -m pytest -q` | All tests (`firmware/` excluded) | none |
| `python app.py --keyboard --mock` | Arrows, arrow keys stand in for the rider, fake port | none |
| `python app.py --gaze --mock` | Arrows by gaze, fake port | eye camera |
| `python app.py --keyboard --serial PORT` | Same with real motors | HUMANS ONLY |
| `python -m vision.object_select` | Look at objects, dwell to confirm, nothing drives | both cameras |
| `python -m vision.object_select --confirm key` | Confirm with J | both cameras |
| `python -m vision.object_select --confirm jaw --jaw-board synthetic` | Jaw flow on BrainFlow's fake board; J injects a fake clench | both cameras |
| `python -m vision.object_select --confirm jaw --jaw-port /dev/cu.usbserial-...` | Real headset | cameras + headset, HUMANS ONLY |
| `python -m vision.object_select --drive --mock` | Full drive loop into the fake port | both cameras |
| `python -m vision.object_select --drive --serial PORT` | Full drive loop, real motors | HUMANS ONLY |
| `python -m vision.nav_preview` | Route preview, no motors | forward camera |
| `python -m vision.detect_track --source 1 [--gemini]` | Boxes, distances, optional Gemini ranking (needs a key in `.env`, sends frames to Google) | forward camera |
| `python -m vision.camera_view --synthetic --seconds 10` | Camera viewer on test frames | none |
| `python -m vision.gaze_calibrate --eye-camera 0` | Calibrate the built-in tracker | eye camera |
| `~/venvs/eyetrax/bin/python -m vision.gaze_tracker_eyetrax --calibrate-only` | Calibrate EyeTrax | eye camera |
| `python -m bci.jaw_live --synthetic` | Jaw test on the fake board | none |
| `python -m bci.jaw_live --dongle PORT` or `--wifi` | Jaw test on the real headset | HUMANS ONLY |
| `python -m interface.flicker [--single 12] [--seconds 60]` | The flicker screen (photosensitivity warning first) | screen |
| `python firmware/hoverboard/tools/bridge_bench_test.py PORT` | Wheels-up bench test | HUMANS ONLY |

Settings: `GAZE_BACKEND=builtin|eyetrax`, `YOLO_MODEL`, `GEMINI_API_KEY` (in the git-ignored `.env`), models in
`~/hp26-models/`. Commands named in `README.md` and `AGENTS.md` that do not exist: `python tools/smoke.py`,
`python app.py --synthetic --mock`, `python app.py --cyton --serial ...`.

Test run I made on a clean export of commit `1711282`: `python -m pytest -q` gave `285 passed, 8 warnings in
30.65s`. Per file: state machine 53, app 22, gaze 25, protocol 23, bridge protocol 17, object_select 17,
detect_track 12, camera_source 11, destinations 10, nav_preview 10, navigation 9, driver 9, jaw 9, timing 9,
goto 7, flicker 7, the rest 5 or fewer each.

---

## 8. What is verified, and where

| Piece | Real hardware (per repo notes, not re-run by me) | Simulation or mock port | Not working or no evidence |
| --- | --- | --- | --- |
| Safety state machine | | 53 tests, plus end-to-end tests through the mock port | never run against real wheels with a rider |
| Motor driver and line protocol | left wheel answered the laptop (PROGRESS.md) | 26 tests | |
| Bridge sketch | left wheel: forward, back, turn, watchdog stop (PROGRESS.md), but with a newer sketch that is not in the repo | I compiled the repo sketch's logic on the laptop with a fake clock: watchdog, obstacle rule, clamp, malformed lines, clock wrap all behave as documented | ultrasonic stop, right wheel, both wheels together |
| Hoverboard firmware | flashed and verified on the master board; halls mapped | | slave board; current sense and self-hold pins unverified (`firmware/README.md`) |
| Gaze on arrows | one live run: all 4 directions reached MOVING, 11 of 23 selections, on the mock port | tests | accuracy in the real chair seat |
| Gaze on objects | "3 confirmations, 0 false" (`docs/GAMEPLAN_SAT.md`) | tests | |
| Object detection | 19.7 detections per second on the Pixel in one 45 s run; 6 to 9 when the laptop was busy | tests on pure functions | |
| Distance estimate | "chair at 1.55 m reads 1.55 m": this is the calibration point itself, not an independent check | | any second distance, any other object |
| Drive to object | | one end-to-end test with fake camera, YOLO and gaze into the mock port; planner tests in an ideal world | never run with a real camera feeding real wheels, not even wheels-up |
| Jaw clench | | synthetic signals only; 4 of 4 fake clenches | zero clenches recorded from a real head; headset has not given a usable signal |
| SSVEP (brain signal) | one recording: no peak | flicker screen tests | no decoder exists; the 60 FPS timing gate on the real screen has no recorded result |
| Closed-eyes emergency stop | | | does not exist |
| Ultrasonic sensor, kill switch, chassis | | | no evidence in the repo |
| Route preview | "live frame rendered" (PROGRESS.md) | tests | being rebuilt; camera height and tilt are guesses (1.0 m, 15 degrees) |

---

## 9. Findings, most severe first

All proofs ran against commit `1711282` with the camera, YOLO, eye tracker, headset and serial port faked, and
the project's real selection logic, planner, state machine, driver and `MockSerial`. Scripts are in the scratch
folder named in section 13. None of this is a measurement on the real chair.

### Finding 1 (HIGH, PROVEN): a frozen forward camera keeps the chair driving on the last picture
- What breaks: if the forward camera stops delivering frames, the chair keeps driving toward where the object
  was, for as long as the rider keeps looking at the (frozen) box on screen.
- Why: `LatestFrameReader.latest()` returns the last frame forever. `run()` in `vision/object_select.py`
  never checks how old that frame is, and builds every `Intent` with `t=now`, so the state machine's "stale
  after 0.5 s" rule can never fire. The same is true in `app.py`: every caller stamps the intent with the
  current time, so that rule is exercised only by tests. The forward camera is the part the team itself calls
  flaky.
- Proof: `proof_frozen_camera.py`. The fake camera delivers frames for 0.5 s and then repeats the last one.
  Output: `camera froze at t=0.49 s; YOLO ran 19 times, last at t=0.49 s`, then the object was confirmed and
  `drive lines (C,...) sent: 93; first at t=3.05 s, last at t=7.98 s`, `last drive line: 'C,149,99,99', sent
  when the newest camera frame was 7.5 s old`. The whole confirmation and drive happened after the freeze.
- Fix: in `run()`, when the newest frame is older than `STALE_INTENT_S`, empty the target list and stamp the
  intent with the frame's arrival time instead of `now`, so the existing stale rule stops the chair.

### Finding 2 (HIGH, PROVEN in simulation): the chair cannot tell when it has reached a chair, table or person, and cannot see a person as a close obstacle
- What breaks: "stop 0.7 m from the object" never happens for 9 of the 16 object types, including chair,
  dining table and person. The planner keeps commanding forward until something else stops it. A person
  standing in or beside the path is never avoided.
- Why: distance = typical height x focal length / box height, and a box cannot be taller than the picture. So
  the estimate has a floor: at 1920x1080 and 85.5 degrees a chair can never read under 0.87 m, a dining table
  0.72 m, a person or refrigerator 1.63 m. `ARRIVE_M` is 0.7 m. The planner only refuses a path that comes within
  0.45 m of an obstacle during the next 0.6 m of travel, so it can refuse nothing that reads farther than
  1.05 m; a person always reads at least 1.63 m.
- Proof: `proof_planner.py`: `1920x1080: 9 of 16 drivable classes can never read < 0.7 m: dining table (min
  0.72 m), toilet (0.72), bench (0.77), couch (0.82), chair (0.87), sink (0.87), bicycle (0.96), person (1.63),
  refrigerator (1.63)`. `proof_closed_loop.py` drives an ideal chair with the project's `nav_step()` and a
  camera model whose boxes are clipped by the frame, ultrasonic off: potted plant and suitcase `arrived ...
  closest 0.70 m`; chair, dining table and person `chair centre reached the object (collision) ... planner said
  ARRIVED: False ... wheels at that moment (99, 99), estimate still 0.87 m` (0.72 m, 1.63 m).
  `proof_closed_loop_pipeline.py`, a person standing 0.4 m beside the straight line to the target: `HIT the
  obstacle after 6.1 s at wheels (101, 101) (obstacle's distance estimate at that moment: 1.63 m)`, with or
  without the person in the planner's obstacle list.
- Also: the 85.5 degree calibration lives in the git-ignored `data/raw/camera_calibration.json`. On any other
  clone `load_hfov()` returns 70 and every distance reads 1.32 times too far (I computed the focal lengths:
  1371 vs 1039 pixels); a frame-filling chair then reads 1.14 m.
- Fix: treat a box that touches the top or bottom edge of the frame, or fills most of its height, as "too close
  to measure" and stop; and until the ultrasonic stop is proven on the chair, do not rely on `ARRIVE_M` for tall
  objects.

### Finding 3 (HIGH, PROVEN): no operator stop key in `object_select --drive`, and X does nothing in the default mode
- What breaks: a teammate who presses SPACE (the emergency stop in `app.py`) during an object drive gets no
  reaction. X, documented as "cancel confirmation", has no effect in dwell mode while the rider keeps looking
  at the object. The latched `E_STOP` state cannot be reached in this program at all.
- Why: `run()` handles only C, X, J, Q and ESC, and `drive_tick()` never passes a `StopRequest`. In dwell mode,
  X clears `sel.confirmed`, but the dwell timer `sel.since` is not reset, so `update_selection()` confirms the
  same object again in the same loop pass, before the drive step sees the cancel.
- Proof: `proof_operator_keys.py`. Dwell mode, chair moving since t=3.04 s: `t=4.0-5.0 (SPACE held 4.0-4.3 s):
  19 drive / 0 stop lines`, `t=5.0-5.4 (X held 5.0-5.3 s): 7 drive / 0 stop lines`, and 12 "CONFIRMED" lines
  logged. Key mode: SPACE again 19 drive / 0 stop; X works (`0 drive / 7 stop lines`, stays stopped).
- Fix: in `run()`, turn SPACE into `StopRequest(StopSource.OPERATOR, now)` passed to `step()` and R into the
  re-arm, exactly as `app.py` does; on X also clear `candidate` and `since`.

### Finding 4 (HIGH, PROVEN for the repo, QUESTION for the hardware): the bridge sketch on the ESP32 is not in the repository, and the wiring notes disagree
- What breaks: the safety rules that live on the ESP32 (200 ms watchdog, obstacle stop, speed clamp) can only
  be reviewed in a sketch that is not the one running. PROGRESS.md (Sat evening) and
  `firmware/hoverboard/DEBUG_LOG.md` say the working bridge auto-detects TX/RX, prints `#` lines and uses a
  file `hover_link.h`, and ask Keshav to push it. No branch contains `hover_link.h` or any auto-detect code
  (`git grep` over all local and remote branches). The repo sketch prints no `#` lines.
- Also: `firmware/README.md` and the sketch header tell you to wire the 4-pin plug. The debug log says the
  4-pin plug is a dead end and the link is the 5-pin plug, where P5 carries about 14 V. Someone following the
  README wires the wrong connector.
- Fix: push the flashed sketch tonight, correct the README and sketch header to the 5-pin plug, and repeat the
  three bridge checks (silence stops the wheels, hand in front of the sensor stops forward but not a turn,
  speed above 150 is clamped) on that exact sketch.

### Finding 5 (HIGH until tested; code behaviour PROVEN, hardware QUESTION): the ultrasonic stop is the only backstop for findings 1 and 2, it fails open, and there is no record it was ever tested
- What breaks: with no sensor fitted, a broken wire, or a soft or angled surface that returns no echo, both the
  bridge and the laptop read "nothing in range" and allow forward motion. The laptop also allows motion when it
  has never received a single distance line.
- Why: echo timeout maps to -1 (clear) by design, and `forward_blocked(None)` is False.
- Proof: `proof_jaw_and_misc.py`: `distance_cm=None: after 2 s of FORWARD -> state MOVING, wheels (150, 150)`,
  same for -1, STOP for 30. Host run of the sketch: `echo timeout (no sensor / nothing in range), forward ->
  wheels L=100 R=100 D,-1,OK`. A test (`test_no_block_for_unknown_timeout_or_far_distance`) fixes this
  behaviour on purpose. The repo has no entry showing the sensor wired or tried.
- Fix: before any drive session require one positive reading (wave a hand in front of the sensor) and refuse
  `--drive --serial` without it; in drive mode treat "no distance line for 0.5 s" as blocked.

### Finding 6 (MEDIUM, PROVEN): the planner only knows about the boxes shown on screen
- What breaks: an object that is not one of the (at most 4) displayed boxes is not an obstacle. That includes a
  fifth object, anything detected with confidence under 0.4, anything outside the 16 classes, and, by
  construction, anything whose box overlaps or sits within 5% of the frame width of a better-ranked box. That
  last rule was written to keep flickering boxes apart; in drive mode it removes exactly the things standing
  next to the target. `control/goto.py` says "every object the camera sees other than the target".
- Proof: `proof_planner.py`: five tracks, `targets kept for the screen AND for the planner: couch#2, chair#1,
  tv#4, potted plant#3`, `person among them: False`. `proof_closed_loop_pipeline.py`: an obstacle beside the
  target was dropped from the planner in 40 to 45 consecutive frames.
- Fix: pass the full `tracks` list from `detect()` to `nav_step()` as obstacles, not `targets`.

### Finding 7 (MEDIUM, PROVEN): no soft start; motion also resumes at full command after a cable glitch
- What breaks: the first command after the 1.5 s hold is already the planner's top speed, and the same happens
  each time motion resumes. The 0.3 m/s^2 limit in `NavConfig` has no effect.
- Why: `drive_tick()` runs the planner on every loop pass, also while the state machine is holding the wheels
  still, so the planner's idea of its own speed ramps up during the hold. The planner assumes 0.1 s per step
  but is called once per loop pass, whatever that takes.
- Proof: `proof_planner.py`: `loop at 20 Hz: planner speed 0.5 s into the 1.5 s hold (wheels still stopped) =
  0.31 m/s; first drive command at t=1.50 s = wheels (99, 99)` where top speed is (101, 101); a real ramp
  would need 1.33 s. `proof_reconnect.py`: port fails while MOVING, a new port opens one second later, first
  line on it is `C,20,150,150`, with no new hold.
- Fix: reset `NavState()` whenever the state machine is not `MOVING`; decide whether a reconnect should require
  a new hold.

### Finding 8 (MEDIUM; numbers PROVEN, effect on the wheels LIKELY): the planner's turn-in-place and slow speeds fall inside the board's dead band
- What breaks: `firmware/bridge/bridge.ino` and `vision/nav_preview.py` both note that the board ignores
  speeds between -50 and 50. The fastest in-place turn the planner can request is (-49, 49). Forward speeds
  under 0.2 m/s map to under 50. So the planner's "rotate to find a way round" move, and any slow creep, would
  not move the wheels, while the planner believes it is turning.
- Proof: `proof_planner.py`: `fastest in-place turn the planner can ask for (40 deg/s): wheels (-49, 49)`;
  `straight at 0.19 m/s -> wheels (48, 48)`; with something 60 cm ahead, 40 steps of commands stayed within
  `left 7..49, right -49..-7`. The sketch passes such values through unchanged (host run: `C,1,-49,49 ->
  wheels L=-49 R=49`).
- Fix: confirm the dead band on the left wheel (send 45, then 55), then rescale `to_wheels()` so the smallest
  non-zero command is above it.

### Finding 9 (MEDIUM, PROVEN): jaw calibration accepts a dead signal
- What breaks: `bci/jaw.py` says calibration "refuses ... so a broken headset can never confirm anything" and
  the Devpost draft repeats the idea. A flat signal passes with a threshold of zero and produces one confirmation 0.3 s
  after the detector starts; after that the detector can never fire again, silently.
- Why: `calibrate_threshold()` tests `clench < 3 x relaxed`. With relaxed = 0 that is `0 < 0`, which is false,
  so it accepts. The check has no floor.
- Proof: `proof_jaw_and_misc.py`. At 250 Hz (the dongle rate): all zeros, and a constant -187500.02 uV (the
  railed value the team recorded), both give `calibration ACCEPTED, threshold=0, confirms in 20 s of the same
  dead signal: 1 (first at 0.3 s)`. Railed during the relaxed phase and 5 uV noise afterwards: accepted at 250
  and 1000 Hz. A constant railed value at 1000 Hz is refused (rounding noise makes the ratio 1.0).
- Context: there is no real-head data at all. A false confirmation matters because the only other condition
  for motion is looking at the same object for 1.5 s more. At 250 Hz the detector uses 4 frequency bins (40, 80,
  90, 100 Hz); at 1000 Hz, 8.
- Fix: refuse calibration when the relaxed level is zero or the samples are constant; require a threshold
  above zero.

### Finding 10 (MEDIUM, LIKELY): pulling the USB cable is a 500 ms stop, not a 200 ms one
- The docs (`firmware/README.md`, PROGRESS.md, `docs/TEAMMATE_GUIDE.md`) say unplugging the laptop stops the
  wheels within 200 ms. The 200 ms watchdog runs on the ESP32. Nothing in the repo gives the ESP32 any power
  source other than the laptop's USB cable, so unplugging it switches the watchdog off with it. What then stops
  the wheels is the board firmware's own 500 ms timeout. Keshav's own to-do says "pull USB mid-drive (stop <
  0.5 s)". The 200 ms figure is right only for a laptop that hangs with the cable in. In my host run the
  sketch's zero frame came 213 to 250 ms after the last line, because the rule is checked every 50 ms.
- Fix: correct the docs to "about 0.25 s if the laptop hangs, about 0.5 s if the cable is pulled", and measure both.

### Finding 11 (LOW, PROVEN): claims in the docs that the code does not back up
| Where | Claim | What the repo shows |
| --- | --- | --- |
| `docs/DEVPOST.md` | "Looking at the centre or away stops it within 50 ms" | No end-to-end timing exists. One control tick alone is 50 ms; before it come a camera frame, smoothing and an 8% exit margin; after it up to 50 ms in the driver and 50 ms in the bridge |
| `docs/DEVPOST.md` | "calibration refuses to start unless a clench is at least three times stronger than rest" | finding 9 |
| `docs/DEVPOST.md` | "A state machine running 20 times a second" | true in `app.py`; in object mode it runs once per video loop pass, at whatever rate that is |
| `docs/SAFETY.md`, `docs/DEMO.md` | closing the eyes latches an emergency stop | not implemented; closed eyes stop without latching |
| `AGENTS.md`, `README.md` | `python tools/smoke.py` before every merge; `app.py --synthetic`, `--cyton` | none exist |
| `AGENTS.md`, `docs/ARCHITECTURE.md`, `docs/GLOSSARY.md`, `docs/QUESTIONS.md` | 36 V pack, 8-byte frames, EFeru firmware, Cyton at 250 Hz feeding a CCA decoder | 7 cells at about 28 V, 9-byte frames, RoboDurden firmware, no decoder |
| `docs/GAMEPLAN_SAT.md` | "Distance estimate: CALIBRATED ... chair at 1.55 m reads 1.55 m" | that is the single point the calibration was fitted to |
| `docs/GAMEPLAN_SAT.md` vs PROGRESS.md | hoverboard link "BLOCKED" vs "LEFT wheel WORKS" | the game plan is older |
| PROGRESS.md team board | "Current phase: 0 - Prep" | stale |
| `vision/object_select.py` docstring | "nothing drives the chair from here yet" | `--drive` does |
| `docs/JAW_CONFIRM.md` step 5 | SPACE as the stand-in confirm key | the key is J |
| `docs/INTERFACES.md` | `TargetSet` and `GoalHint` travel over UDP; vision never touches wheel speeds | never sent; `vision/object_select.py` owns the motor driver in drive mode |

### Finding 12 (LOW, PROVEN): a slow video loop makes the chair stutter
The driver sends STOP when the newest command is older than 0.2 s, and object mode hands it one command per
loop pass. `proof_slow_loop.py`: at 50 and 150 ms per pass, 0 interruptions; at 220 ms, 7 drive-to-STOP flips
in about 4 s of motion; at 300 ms, 11. PROGRESS.md records detection at 6 to 9 per second (110 to 170 ms) on a
busy laptop. Each restart is at full command (finding 7). Safe direction, rough ride. Fix: close other apps for
the demo, or run YOLO on a thread and keep the control loop at a fixed 20 Hz.

### Finding 13 (LOW, PROVEN): the "do not send motor lines to the headset" guard knows one name
`looks_like_openbci_dongle()` matches only `usbserial-DM`. `proof_jaw_and_misc.py`: `/dev/cu.usbserial-DN0096XA`,
`-DQ007UBV`, `-D200PMA1` and `COM3` are all accepted as motor ports. Check the real dongle's name; better,
require the bridge to answer with a `D,` line before the first `C` line is ever sent.

### Finding 14 (LOW): quiet failures
- PROVEN: in dwell mode, once the chair has arrived and the rider keeps looking, the object is re-confirmed and
  re-"arrived" on every loop pass (`proof_arrival_loop.py`: 146 CONFIRMED and 146 ARRIVED lines in 5 s, 0 drive
  lines). Harmless for the wheels, floods the log and the summary.
- LIKELY: the jaw thread (`JawConfirmSource._run`) and the control thread in `app.py` (`control_loop`) have no
  error handling. If either dies, the wheels stop or confirmations stop, and the screen keeps showing the last
  state with no message.

### Findings I could not settle (QUESTION)
- Whose eyes: the trackers take one face. If a judge leans into the eye camera's view, is their gaze used?
- Freshness of gaze is "a datagram arrived in the last 0.5 s", not "a new camera frame was analysed". If the
  eye camera ever repeats a frame instead of failing, a frozen gaze would hold the chair in motion. Does it?
- What speed, in metres per second with a rider, does wheel command 101 give? The planner assumes 0.4 m/s. If
  the real chair is faster, the planner's 1.5 s look-ahead and its clearances are too short.

### Tests that pass without proving the thing that matters
- The planner tests (`control/tests/test_navigation.py`, `test_goto.py`) use exact obstacle positions and an
  ideal chair. They prove the algorithm, not the chain camera estimate to planner. Finding 2 lives in that gap.
- The jaw tests build the "clench" as noise 8 times stronger than rest, so "a clench is much stronger than
  rest" passes by construction. No test contains speech, chewing or motor noise, and the pure detector tests
  run only at 1000 Hz.
- `test_bad_contact_fails_calibration_clearly` uses noisy data in both phases. The flat case (finding 9) is
  not covered.
- Not covered anywhere: frozen camera while driving, operator keys while driving, X in dwell mode, arrival for
  tall objects, the dead band, a slow loop, the constants in the sketch versus `shared/protocol.py`.

---

## 10. Things I expected to be broken that are handled correctly

- State machine: no path from a non-`MOVING` state to a non-zero command; exceptions give STOP; a stale intent
  cannot clear `E_STOP`; re-arm needs 0.5 s of quiet; output is clamped. (read, and 53 tests pass)
- Driver: a failed write does not kill the thread; it reopens the port; an old distance is reported as
  unknown; `#` lines are ignored; it never guesses a port. (tests)
- Bridge sketch in the repo, logic compiled and run on the laptop with a fake clock: boots stopped; zero frame
  213 to 250 ms after the last valid line; obstacle rule also catches arcs with net forward speed (150, -140)
  while allowing turns and reverse; clamp to 150; nine kinds of malformed line and an over-long line all zero
  the wheels; CRLF and lines split across reads work; survives the millisecond clock wrapping round.
- Gaze link: samples are stamped on arrival by the receiver, so the two programs' clocks never have to agree;
  bad datagrams are dropped whole; a dead tracker ends the object session; the tracker exits if its parent
  dies.
- Jaw events cannot pile up: a clench while looking at nothing, or within 0.3 s of landing on a box, is thrown
  away; a held clench fires once.
- The tracker-relabel rule in `update_selection()` cannot move a confirmation between two different displayed
  objects in one frame, because displayed boxes are kept apart. (reasoned, not run)
- `pytest.ini` keeps the hardware bench script, which opens a serial port when imported, out of test runs.
- `.env` is git-ignored and not tracked. Gemini is nowhere in the drive path at this commit.

---

## 11. Notes on `docs/ROUTE_REQUIREMENTS.md` (the rebuild in progress, not audited as code)

- C9 says STOP always works by click or key. At this commit the drive program has no stop key at all (finding
  3). C9 needs to reach the state machine as a `StopRequest`, not only the preview.
- The document says the drawn route is "not yet the route the chair drives". A route that passes checks C1 to
  C3 and is drawn solid will read as "the chair will go here safely" to a rider and a judge. C12 labels where
  the floor came from, not this. Put "preview, the chair does not follow this line" on the screen.
- C6 discards Gemini's answer when the view changes or after 10 s, and the first answer took 11.7 s (its own
  figure). A moving chair changes the view all the time, so while driving the floor is always the local guess:
  everything below the horizon that the detector has no mask for. Walls, glass and table legs count as floor
  there. "Verified" then means "does not cross a detected object", nothing more.
- C2 (the chair fits) scales chair width by image row from the camera height and horizon. Both come from
  unmeasured defaults (1.0 m, 15 degrees).
- C11 asks for 15 frames per second with a segmentation model on every frame. The plain detector was recorded
  between 6 and 19.7. Measure before promising it.
- The mouse stands in for the eyes in the preview. Make sure it can never do so when `--drive` is on.

---

## 12. Hard questions for the team

1. Which sketch is on the ESP32 right now? Does it still have the 200 ms watchdog, the obstacle rule and the
   clamp? Is the ultrasonic sensor wired, and has anyone seen it stop a forward command? Is the kill switch in
   the battery line?
2. When the chair drives to a chair, a table or a person, what is supposed to stop it, given the estimate
   cannot go below 0.87 m, 0.72 m and 1.63 m? Has `object_select --drive` ever run with the real camera, even
   wheels-up?
3. Who is the operator during an object drive, and which key do they press to stop it? Today SPACE does nothing
   and X does nothing in dwell mode.
4. Is the dead band (speeds under 50 ignored) real on the flashed board firmware?
5. How is the ESP32 powered? If only from the laptop, the unplug test is a 500 ms test.
6. Jaw clench: what are the real numbers on a head (10 clenches, 30 s of talking, one 5 s hold)? What happens
   to the signal while the motors run and the chair rolls over a bump?
7. What does wheel command 100 mean in metres per second with a rider on board?
8. After a cable glitch, a camera stall or a tracker hiccup, should the chair start again by itself, at full
   command, without a new 1.5 s hold?
9. What resolution and orientation does the forward camera deliver in the demo, and where is it mounted? The
   calibration file is not in git: is it on the demo laptop?
10. What gets submitted? `main` has none of this code, and `AGENTS.md`, `README.md`, `docs/DEMO.md` and
    `docs/SAFETY.md` describe a product (flickering arrows, brain signals, closed-eyes stop) that is not what
    will be shown.

---

## 13. How this audit was done

- Read: `AGENTS.md`, `PROGRESS.md`, the plan, every file in `docs/`, and all code in `app.py`, `shared/`,
  `control/`, `motors/`, `bci/`, `vision/`, `interface/`, `firmware/bridge/`, plus the firmware notes.
- Exported commit `1711282` with `git archive` into a scratch folder so that other agents' unfinished edits
  could not affect results, and ran the tests and proofs there. The safety-path files (`app.py`, `shared/`,
  `control/state_machine.py`, `control/goto.py`, `control/navigation.py`, `motors/`, `bci/`,
  `vision/object_select.py`, `firmware/`) were identical in the working tree at the time.
- The bridge sketch was not uploaded or run on an ESP32. Its logic was compiled for the laptop with `clang++`
  against a small stand-in for the Arduino functions it calls, with a fake clock and fake ports.
- No serial port, camera, headset or network service was opened. `.env` was not read.

Scratch folder (temporary, outside the repo):
`/private/tmp/claude-501/-Users-prakharjain-HP-Auto-WheelChair/730d9cb8-b3b0-47cf-91a2-5b3ee5c324c7/scratchpad/agent_audit/`

| File in `proofs/` (run from the exported `head/` folder with `PYTHONPATH=.:../proofs`) | Finding |
| --- | --- |
| `proof_frozen_camera.py` | 1 |
| `proof_planner.py`, `proof_closed_loop.py`, `proof_closed_loop_pipeline.py` | 2, 6, 7, 8 |
| `proof_operator_keys.py dwell` and `... key` | 3 |
| `proof_jaw_and_misc.py` | 5, 9, 13 |
| `proof_reconnect.py` | 7 |
| `proof_slow_loop.py` | 12 |
| `proof_arrival_loop.py` | 14 |
| `../esp32sim/sim.cpp` with `Arduino.h` | sections 6 and 10, findings 5, 8, 10 |

If the team wants to keep them, findings 1, 3, 6, 7 and 9 each turn into a short failing test in the matching
`tests/` folder, which then passes once the one-sentence fix is in.
