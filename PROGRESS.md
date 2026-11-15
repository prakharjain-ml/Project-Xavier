# PROGRESS.md

Live state for humans and agents. Edit only your own section. Newest entry first. Update before you switch agents,
sleep, or merge. Write for a reader who has seen nothing: name files and functions.

## Team board (owner: Prakhar)
- Current phase: 0 - Prep | Next gate: Gate 0 (all laptops pass import + rules test)
- Saturday plan: `docs/GAMEPLAN_SAT.md` (status table, first 30 min checklist, schedule, decisions for 11 am). Overnight work is on local branch `prakhar/overnight-mode1` (not pushed).
- Last sync: - | Next sync: Fri 8:00 pm kickoff
- Gate log:
  - Gate 0: [x] Prakhar (toolchain + rules + OpenBCI GUI + YOLO cache + ffmpeg verified) [ ] Keshav [ ] Pratosh [ ] Vani
- Decisions: D1 to D8 are locked in section 6 of the plan. Record any change here with time, reason and who agreed.
  - Fri Nov 13, 2:45 pm (pre-kickoff spec reconciliation, Prakhar): Set Phase 1 kickoff constants in `docs/INTERFACES.md` (`CONF_THRESHOLD=0.15`, `MAX_SPEED=150`, `TURN_SPEED=120`, `OBSTACLE_STOP_CM=50`, `ALPHA_BAND_HZ=(8,13)`), made ultrasonic forward-obstacle stop non-latching (`STOPPED` when `(left + right) > 0` and `0 < distance_cm < OBSTACLE_STOP_CM`, `-1` on echo timeout) so in-place turns are never deadlocked, and aligned `docs/` + `.cursor/rules/` ahead of the 8:00 pm initial commit.
  - Sat Nov 14, ~3:00 am (Prakhar, via Claude Code; CONFIRM at 11 am sync): added `GoalHint` (vision -> control, Mode 2) and the JSON-over-UDP transport rule (`"v"` + `"type"`, invalid messages dropped) to `docs/INTERFACES.md`; `shared/protocol.py` updated with a doc-parity test. Reason: vision must never send wheel speeds, so a hoverboard or firmware change only touches `motors/` and `firmware/`.
- Open questions: section 12 of the plan (venue permission, exact hardware). Paste each answer here when it arrives.
- Blockers: **EEG signal not usable yet** (Sat ~9 am analysis of `data/raw/BrainFlow-RAW_15hz_0.csv`): board streams at ~1000 Hz (not 250); huge 60 Hz hum on ch1/2/3/8 (bad contact or loose reference/bias clip); ch2==ch3 and ch5==ch6==ch7 (bridged or unconnected); no 15 Hz peak (SNR ~1). Fix electrodes, re-record, need SNR > 2 at 15 Hz before the decoder can drive.

---

## bci/ (owner: Vani)
### Sat Nov 14, ~8:18 PM - Claude Code (Fable 5.2), for Prakhar (first real-head jaw recording, loose-electrode guard)
- Measured (Prakhar, electrodes on both temples, N1P / N2P, Wi-Fi shield, about 1000 Hz, 73 s, `~/Documents/OpenBCI_GUI/Recordings/OpenBCISession_2026-11-14_20-09-05/`): relaxed 6.7 uV in the muscle band, clench 97 uV, ratio 14.5x (minimum is 3x). Channel 1 never railed; channel 2 railed in 0.5% of samples (its electrode came off for about 11 s). Three gaps in the stream, about 413 samples lost in total.
- Offline, same detector as the live program: 13 confirms in the clench block (10 to 42 s), evenly 2 to 3 s apart. Prakhar's count afterwards, from memory ("pretty sure"): 13 clenches in that block and 6 more in the last 15 s, talking in between. On that count: 19 of 19 clenches confirmed, 0 false confirms in about 22 s of relaxing and talking (with the loose-electrode guard). One recording, one rider, not counted live: quote it as "19 of 19 in one 73 s test", not as an accuracy percentage.
- Bug found and fixed: while the electrode was off and being pressed back (42 to 53 s) the detector confirmed 4 times. New guard (`ARTIFACT_RATIO = 4`): a window more than 4x the rider's calibrated clench is treated as a bad signal, cannot confirm, and blocks confirms for 1 s. On this recording that gives 0 confirms in that stretch and leaves the others unchanged.
- Evidence: `python -m pytest -q bci/tests` -> 48 passed; with the guard switched off the new test's loose-electrode signal confirms.
- Still to do by a human: the live run (`python -m bci.jaw_live --wifi --channels 1,2`) with counted clenches and 30 s of talking.

### Sat Nov 14, ~6:45 PM - Claude Code (Fable 5.2) with subagents, for Prakhar (audit fixes: jaw confirm)
- Done: calibration refuses a dead or railed headset (all zeros, or the constant railed value, used to give threshold 0 and a confirm 0.3 s after start). At run time a flat or railed window never counts toward a clench, cancels one in progress, and blocks confirms for 1 s. A crashed reader thread is logged and visible through `source.alive()` / `source.error`.
- Strict on purpose: one bad window on any channel in use fails calibration. With channels 1,2 and channel 2 railed, fix the electrode or pass `--jaw-channels 1`.
- Not fixed, known: strong mains hum from a detached (not railed) electrode can still look like a clench (2 mV of 60 Hz read as 10x the relaxed level in a synthetic check). A board that stops sending samples is still silent. Still no real-head jaw data in the repo.
- Evidence: `python -m pytest -q bci/tests motors/tests` -> 101 passed (was 40); 7 mutation checks each fail a test.

### Sat Nov 14, ~1 pm - Claude Code (Opus 5.5), for Prakhar (Vani: please review, it is in your folder)
- Done: `bci/jaw.py` (jaw-clench EMG detector: 40-200 Hz energy per 0.1 s, +-12 Hz mains guard, held >= 0.3 s, once per clench, refuses to calibrate if clench < 3x relaxed) and `bci/jaw_live.py` (live test: --dongle PORT / --wifi / --synthetic practice). Step-by-step: `docs/JAW_CONFIRM.md` (incl. Wi-Fi dropouts: battery, Auto-Join, prefer the USB dongle).
- Next step (HUMAN): fix railing (ear clips), then `python -m bci.jaw_live --dongle /dev/cu.usbserial-...`; pass = 10 clenches -> 9-10 CONFIRMs, 30 s talking -> 0.
- Evidence (command + result): `python -m pytest -q bci/tests` -> 12 passed; `python -m bci.jaw_live --synthetic --seconds 20` -> 4 fake clenches -> `summary: confirms=4` (at 250 Hz).

### [time] - [model/agent]
- Done:
- In progress (file:function, state):
- Next step:
- Known bugs:
- Evidence (command + result):

## interface/ (owner: Prakhar)
### Sat Nov 14, ~3:00 am - Claude Code (Opus 5.5), for Prakhar
- Done: `interface/timing.py` (frame-counted `is_on`, `flicker_schedule` 9/7/5/4, `FrameStats` drop/slow counters) and `interface/flicker.py` (photosensitivity warning -> SPACE, four arrows, static outlines, dwell bars from a latest-only `ControlStatus` queue, E-STOP banner, F toggles stats, `--single 12` for task 2.10, `--fake-status` for 2.8, `--seconds N` prints the timing summary). No cv2, no sleep in the render loop.
- In progress (file:function, state): none.
- Next step (HUMAN, on the MacBook screen): `python -m interface.flicker --seconds 60` -> need mean_fps 59.5-60.5 AND `dropped=0` AND no "NO VSYNC" warning (pygame can claim vsync without pacing: seen at ~570 FPS on the dummy driver; the loop now detects this and falls back to exact-deadline pacing); `python -m interface.flicker --fake-status`; then 240 fps phone video per target (2.9). Headless tests prove logic only, not timing.
- Known bugs: none known. Dummy-driver runs have no vsync.
- Evidence (command + result): `python -m pytest -q interface/tests` -> `14 passed`; mutation (bypass warning gate) -> 1 test fails. Caught and fixed a vacuous test ('frames=0' substring matched 'slow_frames=0').

### [time] - [model/agent]
- Done:
- In progress (file:function, state):
- Next step:
- Known bugs:
- Evidence (command + result):

## control/ (owner: Prakhar design, Pratosh integration)
### Sat Nov 14, ~7:34 PM - Claude Code (Fable 5.2), for Prakhar (route following)
- Done: `control/follow.py`: pure pursuit on a route given in metres in the chair's frame. Look-ahead 0.6 m, eases off in bends and over the last metre, turns on the spot when the route is far to the side, never reverses, stop when less than 0.5 m of route is left. No route or a broken route gives (0, 0).
- Evidence: `python -m pytest -q control/tests/test_follow.py` -> 7 passed, including a closed-loop run around a 0.8 m detour (ideal chair, re-planned every step): worst distance off the route 8.4 cm, arrived in 15 s. Look-ahead sweep: 6.5 cm at 0.5 m, 8.4 cm at 0.6 m, 15.6 cm at 0.9 m.
- Never run on the chair. Real latency (camera, loop, motors) will make it wobble more than the simulation; if it weaves, raise `lookahead_m`.

### Sat Nov 14, ~6:45 PM - Claude Code (Fable 5.2) with subagents, for Prakhar (audit fixes: arrival, dead band)
- Done: `nav_step(..., frame_h=...)` now reports ARRIVED when the camera can no longer measure the target getting closer: its box fills 90% of the frame height, or is cut off by the bottom edge and reads 2.5 m or less. A cut-off box reading farther is a stop without arrival. Before, the estimate could never drop below 0.87 m (chair), 0.72 m (table) or 1.63 m (person) against `ARRIVE_M` 0.7 m, and the simulated chair drove into all three. `to_wheels()` keeps every non-zero command at or above the board's dead band (`WHEEL_DEAD_BAND = 50`); the spin was (-49, 49) before.
- Changes behaviour, check on the floor: (1) the chair now stops where the target's foot leaves the picture, about 1.1 to 2.0 m away depending on camera height and tilt, not 0.7 m. A steeper downward tilt brings it closer. (2) Turn-in-place now really moves the wheels (about 41 deg/s). It has never run on hardware. (3) `WHEEL_DEAD_BAND = 50` comes from a comment in `bridge.ino`, not a measurement: send 45 then 55 to a wheel to check.
- Evidence: `python -m pytest -q control/tests` -> 105 passed (was 79); 12 mutation checks each fail a test.

### Sat Nov 14, ~2:30 am - Claude Code (Opus 5.5), for Prakhar
- Done: `control/state_machine.py`: pure `step(prev, ControlInputs, now, mapping)` -> (ControllerState, MotorCommand, ControlStatus); every SAFETY.md row tested (`control/tests/test_state_machine.py`, 53 tests incl. 1,000-intent fuzz and a 20 Hz dwell run). `provisional_mapping` = INTERFACES.md table; Pratosh's `control/mapping.py` (task 2.12) plugs in via `mapping=`.
- Interpretations for the team (please confirm at the 11 am sync): (1) stale/missing Intent does NOT clear E_STOP; only re-arm does. (2) "no active StopRequest" = none in the last `STOP_ACTIVE_S` = 0.5 s, so `bci/alpha.py` must keep sending StopRequest while eyes stay closed.
- Next step: Pratosh: `mapping.py` + wheel-sign check; app.py (task 4.1) calls `step` at CONTROL_HZ.
- Known bugs: none known.
- Evidence (command + result): `python -m pytest -q control/tests shared/tests vision/tests` -> `111 passed`; mutation check (disable obstacle block; let stale clear E_STOP) -> 3 tests fail for each.

### [time] - [model/agent]
- Done:
- In progress (file:function, state):
- Next step:
- Known bugs:
- Evidence (command + result):

## motors/ and firmware/ (owner: Pratosh, with Keshav)
### Sat Nov 14, 9:48 PM - Claude Code (Opus 5.5), for Keshav
- Done: **Both wheels drive from the laptop.** Laptop -> ESP32 -> each board's 5-pin master-slave plug (P2 = PA2 TX,
  P3 = PA3 RX; ESP32 GND to each board's SWD GND hole, because P1 is not a solid ground). Slave unlocked and flashed.
  Both boards run `e235_single_usart1_hold.bin` (option 5: no 8-min auto power-off). `bridge.ino` auto-detects TX/RX per
  board, `RIGHT_SIGN -1`, `MAX_SPEED 910`. Runs on battery. Shell closed.
  New laptop library `firmware/chair_control/` (`from firmware.chair_control import Chair`; `forward/backward/turn_left/
  turn_right/drive/stop(speed, seconds)`, 850 cap, accel ramp, auto-stop on exit), documented in its `README.md`.
- In progress (file:function, state): nothing open.
- Next step: run `python firmware/chair_control/example.py COM4` wheels-up. Then distance and degree moves: forward the
  boards' odometry from `bridge.ino` to the laptop (new line type, needs a `docs/INTERFACES.md` change by its owner).
- Known bugs: no free GD32 pin holds the board's power (searched with `find_hold_pin.py`, HIGH and LOW), so the power
  button is replaced by a **kill key** (jumper on two wires outside the shell: pull = boards off). Pull it when parked
  (battery drain). `docs/INTERFACES.md` "ESP32 to hoverboard" section is still wrong (see `firmware/README.md`).
- Evidence (command + result): `bridge_bench_test.py COM4 120` -> both boards found, both wheels drive the right way
  (Keshav, wheels up, on charger and on battery); `hold_check.py` -> `PA7 mode=OUTPUT out=HIGH` yet board off on
  release; chair_control against a fake port -> ramp 60,120..840,850, clamp 850, stop lines on close;
  `git apply --check robodurden-c63b29a.patch` on clean c63b29a -> clean.

### Sat Nov 14, ~6:45 PM - Claude Code (Fable 5.2) with subagents, for Prakhar (audit fixes: soft start, dongle guard)
- Done (`motors/driver.py`): soft start. A wheel's speed rises by at most `SLEW_STEP = 8` per line (0 to the 150 cap in about 0.95 s at 20 lines/s); any decrease or stop is immediate; a reversal goes through zero; the ramp restarts from zero after a stop, a stale command or a reconnect (the first line after a reconnect was `C,20,150,150`, now `C,20,8,8`). `looks_like_openbci_dongle` refuses any `usbserial-<letter>...` or FTDI name, not only `-DM...`.
- Pratosh please check: the first ramp lines (8 to 48) are inside the board's dead band, so the wheels start at about line 7. A reconnect still resumes driving without a new 1.5 s hold (now from zero). `COM3` and `/dev/ttyUSB0` cannot be told apart from a dongle by name.
- `test_app.py`: the two end-to-end tests now assert the soft-start ramp instead of a first line at the cap.
- Evidence: same run as bci above; 6 mutation checks each fail a test.

### Sat Nov 14, evening - from Keshav's handoff (recorded by Claude Code for Prakhar)
- Done: LEFT wheel (master board) WORKS end to end: laptop -> ESP32-S3 -> board, forward/back/turn + watchdog stop verified. Link = 5-pin plug (P2 TX, P3 RX), ESP32 GND to a SOLID ground (P1 gave 60 Hz hum). Battery is 7S (~28 V).
- In progress: RIGHT wheel (slave board): unlock, motor test, flash `e235_single_usart1.bin`, wire GPIO15/16 + its own solid GND.
- Next step (Keshav): finish the slave, fix wheel signs, retest on battery, pull USB mid-drive (stop < 0.5 s), PUSH the newest local files: `firmware/bridge/bridge.ino` + `hover_link.h`, bench test hold mode, firmware guards.
- Integration: bridge now prints `#` info lines; laptop parser verified to ignore them (new tests); documented in INTERFACES.md.

### Sat Nov 14, ~9:30 am - Claude Code (Opus 5.5), for Prakhar (Pratosh: please review)
- Done: `motors/bridge_protocol.py` (C/S encode with clamp, D parse), `motors/mock_serial.py`, `motors/driver.py` (20 Hz, STOP when no fresh command for 0.2 s, survives unplug + reconnects, never auto-detects ports). `app.py`: keyboard stands in for the decoder (hold arrow = Intent, SPACE = E-STOP, R = re-arm) through the real state machine + driver; refuses ports that look like the OpenBCI dongle (`usbserial-DM`).
- Next step (HUMAN, wheels off the ground, kill switch in hand, after `bridge.ino` is uploaded): `python app.py --keyboard --serial /dev/cu.<ESP32 port>`; hold Up -> dwell bar 1.5 s -> wheels forward; release -> stop; SPACE -> E-STOP; unplug USB -> stop within 200 ms.
- Known bugs: none known. Caught in testing: driver thread crashed if a write failed (fixed); one vacuous stale-command test (fixed, mutation-checked).
- Evidence (command + result): `python -m pytest -q` -> all pass (motors 22, app 10); end-to-end test: held FORWARD reaches the mock port as `C,…,150,150` only after >= 25 STOP lines (1.5 s dwell); removing the dwell fails 2 tests.

### Sat Nov 14, morning - Claude Code (Opus 5.5), for Keshav
- Done: Master hoverboard board (YK187, GD32E235) unlocked over SWD, factory firmware erased, RoboDurden Gen2.x-GD32
  firmware running. Pin map in `firmware/README.md` (halls PF1/PA0/PC15 found by hand-turning the wheel, BLDC normal
  hi/lo, VBATT PA4). Prebuilt `e235_single_uart.bin`, `e235_master.bin`, `e235_slave.bin` + Windows flash scripts in
  `firmware/hoverboard/flash_tools/`; patch to rebuild in `firmware/hoverboard/firmware_src/`.
  `firmware/bridge/bridge.ino` follows the INTERFACES.md laptop protocol (C/S in, D out, 200 ms watchdog, obstacle stop, clamp 150).
- In progress (file:function, state): the USART0 round pads are dead (R10/R11 not fitted), so the setup is now
  `e235_single_usart1.bin` on BOTH boards, each driven by the ESP32 through its own 4-pin master-slave plug
  (`bridge.ino` `DUAL_SINGLE 1`: left board on GPIO17/18, right board on GPIO15/16). Slave board not unlocked yet.
- Next step: beep-test the master's 4-pin plug (PA2 = chip pin 12, PA3 = pin 13, GND, VCC), flash option 1, upload
  `bridge.ino`, run `firmware/hoverboard/tools/bridge_bench_test.py` wheels-up. Then slave: unlock, test03, option 1.
- Known bugs: **`docs/INTERFACES.md` "ESP32 to hoverboard" section is wrong for our firmware** (real: '/' + speed + steer
  + 2 state bytes + CRC16, 9 bytes, 19200 baud; see `firmware/README.md`) - docs owner please update.
  SELF_HOLD PB2 and CURRENT_DC PA6 unverified (bridge the power button for now). VBATT reads ~9% high.
  SWD over hand-held jumpers is glitchy on charger power. `bridge.ino` not compiled yet (human step).
- Evidence (command + result): `7_flash_firmware.bat`-equivalent flashes -> `** Verified OK **`; test03 zigzag spins the
  wheel smoothly (Keshav, wheels up); `hall_watch.py` -> `PA0: 211, PF1: 209, PC15: 205` toggles, sequence
  `010 011 001 101 100 110`; `git apply --check robodurden-c63b29a.patch` on a fresh c63b29a checkout -> clean.

### [time] - [model/agent]
- Done:
- In progress (file:function, state):
- Next step:
- Known bugs:
- Evidence (command + result):

## vision/ (owner: Vani)
### Sat Nov 14, ~9:47 PM - Claude Code (Opus 5.5), for Prakhar (steadier cursor, gliding outlines)
- Prakhar, live: "the cursor shakes around a lot", the screen should be "much much smoother". EyeTrax already applies Kalman + EMA (0.25); still shaky.
- Done (`vision/smoothing.py`): One Euro filter on the gaze point (min cutoff 0.3 Hz, beta 1.0). Synthetic test (2% shake, 30 Hz): fixation shake cut to 0.23 of raw, a full-screen glance lands in 0.10 s. The smoothed point drives both the cursor and which object is under it. Outlines glide 35% of the way to each new detection per screen update instead of jumping 7 times a second (drawing only).
- Evidence: `python -m pytest -q` passes. Not yet judged live.

### Sat Nov 14, ~9:36 PM - Claude Code (Opus 5.5), for Prakhar (gaze screen lag)
- Prakhar, live: "very laggy". Measured per pass at 1920x1080: detection 60 ms (`yolo11s-seg`), route plan 29 ms, drawing 9 ms. Detection ran on every camera frame, so the eye cursor updated only as fast as YOLO.
- Fix (`vision/object_select.py`): detection runs at most every 0.15 s (`DETECT_PERIOD_S`); the camera picture and the gaze cursor update every pass. The direct planner steps only on a new detection (its acceleration limit assumes one step per look); the state machine still runs every pass, so looking away, SPACE and a stale frame stop as fast as before.
- Session result before the fix: gaze available in 92% of frames (8% no sample from the tracker). Gaze quality ("not working very well") not yet diagnosed: offset, jitter or wrong object?
- Evidence: `python -m pytest -q` -> `577 passed`. Not yet re-checked live.
- Known flaky: one test failed once under heavy load (other agents running) and passed on an idle machine; not identified.

### Sat Nov 14, ~9:27 PM - Claude Code (Fable 5.2), for Prakhar (camera roles: biggest face = eye camera)
- Bug seen live: the gaze screen detected objects on the laptop camera (the rider's own face). The Pixel faced a teammate across the table, and the rule "the camera that sees a face is the eye camera" took the Pixel for the eye camera.
- Fix (`vision/camera_roles.py`): the eye camera is the one with the widest face in view (the rider sits closest to the laptop camera); the forward camera may see people. Two faces of about the same size are refused with a message instead of guessed. `--eye-camera N --source M` still override.
- Evidence: `python -m pytest -q` passes; live log after the fix: `cameras: 0 (widest face 0%), 1 (widest face 18%)` -> `eye camera = 1, forward camera = 0` (0 = Pixel, 1 = laptop, checked by saving one picture from each).
- Limit: the mouse preview (`nav_preview`) has no rider at the screen, so it takes the camera with the smallest face, lowest number on a tie. If that picks the laptop camera, pass `--source 0`.

### Sat Nov 14, ~7:34 PM - Claude Code (Fable 5.2), for Prakhar (chair follows the route: `object_select --drive --follow route`)
- Done: in route mode the drive screen plans the route to the chosen object on every camera frame (37 ms at 1920 x 1080), draws it (dashed: local floor only), converts it to metres and hands it to the follower. Default is still `--follow direct` (the older planner). New options `--cam-height`, `--cam-pitch`. The preview's bottom bar now shows what the follower would tell the wheels ("would drive: FORWARD + RIGHT").
- New safety rule C13 (blind strip): an object that runs off the bottom of the picture has its foot in floor the camera cannot see. The route's first point must be far enough to the side of it, or there is no route. Found by checking the hall frame in metres: the route started 1.8 m ahead and 0.56 m right, and the straight run to it passed where the middle chair stands (1.4 m ahead).
- Consequence: both test scenes (hall frame, lounge photo) now give "No safe route". The chairs are 1.4 m away with about 0.9 m between them. To get a route: tilt the phone down about 20 degrees (nearest visible floor about 0.8 m instead of 1.75 m) and keep about 0.5 m clear to each side of the way in.
- Evidence: `python -m pytest -q` -> `571 passed`. End-to-end on a mock port: open floor -> both wheels forward and equal; a barrier across the floor -> no drive lines and "no safe route" on screen; mutation (fall back to the old planner when there is no route) fails that test.
- Docs: `docs/VIDEO_SCRIPT.md` (2-minute video, shot by shot, with fallbacks) and `docs/RUN_OF_SHOW.md` (hour-by-hour to the 10 am demo, three decisions for tonight).

### Sat Nov 14, ~6:45 PM - Claude Code (Fable 5.2) with subagents, for Prakhar (audit fixes in `object_select --drive`, colour floor, better detector)
- Done (`vision/object_select.py`): a frozen forward camera now stops the chair (the Intent carries the frame's arrival time, so the state machine's 0.5 s stale rule fires; before, 87 drive lines went out on a frozen picture). SPACE = latched emergency stop, R = re-arm, X = cancel in every confirm mode (the same object cannot be re-chosen until the gaze leaves it). Arrival is reported once. The planner gets every tracked object as an obstacle, not only the 4 boxes on screen. The session ends if the jaw reader thread dies.
- Done (route preview): the floor is now found by colour (`vision/floor_seg.py`); Gemini's floor outline was too rough (a bottom strip on the hall frame) so Gemini only adds no-go zones for things the detector misses. Detector switched to `yolo11s-seg` (both hall couches at 0.70 / 0.62 confidence vs 0.42 / 0.39 with the smallest model; 27 ms vs 20 ms a frame). Example on a real hall frame: `docs/img/route_preview_design.jpg`.
- Done (gaze screen look): `object_select` now draws the new screen: cyan outline per selectable object, eye cursor, label pill, reticle (fills during the dwell; full = ready to clench), chair state first in the bottom bar. The gaze point is remapped to the camera picture between the two bars (`to_view_point`). No route there yet, and still at most 4 well-separated objects (the hall couches behind the chairs were not offered).
- Not fixed, known: a blink counts as "looked away", so after X or an arrival a rider who keeps staring can re-confirm 1.5 s after a blink. SPACE does not clear the destination (after R the chair can move again after a fresh 1.5 s hold). A camera repeating one picture with new timestamps is not detected.
- Evidence: `python -m pytest -q` -> `554 passed`; `python -m pytest -q vision/tests/test_object_select.py` -> 31 passed; mutation checks for each fix fail a test. Nothing ran on a real port, camera feed for driving, or headset.

### Sat Nov 14, ~6:27 PM - Claude Code (Fable 5.2) with subagents, for Prakhar (route preview rebuilt: outlines, cursor, route on the real floor)
- Done: `python -m vision.nav_preview` is rebuilt in the look of Prakhar's reference image. Every object gets a thin cyan outline from a segmentation model (`yolo11n-seg`, in `~/hp26-models/`; `Track.outline` in `vision/detect_track.py`). The mouse stands in for the eyes: rest it on an object for 1.5 s to choose it. Gemini finds the floor and extra no-go zones in a background thread (`vision/scene_ai.py`). The route is planned locally in a top-down view of the floor in real centimetres and drawn back on the image (`vision/floor_route.py`, `vision/route_scene.py`, screen in `vision/hud.py`). Rules: `docs/ROUTE_REQUIREMENTS.md` (12 constraints). The old blue panel is gone.
- Evidence (command + result): `python -m pytest -q` -> `448 passed`. `python -m vision.nav_preview --image <lounge photo> --cursor 0.87,0.60 --no-window --save out.png` -> `route=8 pts floor=gemini`, saved as `docs/img/route_preview_design.jpg`. Screen draws in about 3.5 ms; planner 2 to 10 ms; Gemini 2.0 to 9.6 s per answer (5 timed calls). Mutation checks for C1, C2, C5, C6 each fail a test.
- Not done: the route on screen is not yet the route the chair drives (motors still follow `control/goto.py`). The real gaze screen (`vision/object_select.py`) still has the old boxes.
- Known limits: Gemini misses objects in some answers; a level camera at 35 in sees no floor nearer than about 1.7 m; detected chair distance read 1.68 to 1.71 m against a measured 1.40 m when the box is cut off by the frame.
- Camera defaults now 0.89 m high, level (Prakhar's table set-up). Re-measure on the chair (`--cam-height`, `--cam-pitch`).

### Sat Nov 14, ~5:31 PM - Claude Code (Fable 5.2), for Prakhar (floor-path HUD for the path preview)
- Done: `python -m vision.nav_preview` now draws the shortest safe path on the floor: `control/astar.py` (A* on a 10 cm grid, obstacles grown by 0.45 m, string-pulled), `vision/floor.py` (floor point -> pixel from camera height + tilt), `vision/hud.py` (blue-gradient ribbon as wide as the chair with flowing arrows, stop ring, corner-bracket boxes, stats panel: target, distance/bearing, path/ETA, clearance, obstacles, speed/turn, motor command, wheel bars). Still sends nothing to any motor.
- Evidence (command + result): `python -m pytest -q` -> `285 passed`; HUD draw time 20 ms per frame (A* 2.7 ms); live frame from the Pixel back camera rendered through the HUD.
- Not measured yet: the phone's real height and tilt on the chair. Defaults are 1.0 m and 15 deg down; pass `--cam-height` / `--cam-pitch` once measured, otherwise the ribbon will not sit exactly on the floor.
- Next step: measure camera height/tilt on the chair; show the same HUD in `object_select --drive`.

### Sat Nov 14, ~noon - Claude Code (Opus 5.5), for Prakhar (gaze fallback works live)
- Done: tracker runs as its own program over localhost UDP (fixes 0-sample bug); straight-line calibration chosen by leave-one-dot-out check (error 0.138 vs 0.232 for the 28-term map) -> calibration accuracy 97%; on-screen gaze cursor + C-key re-centring; bigger arrow regions, enter 2% inside / leave 8% outside.
- Evidence (command + result): `python app.py --gaze --mock --seconds 120` (Prakhar, live): all 4 directions reached MOVING (FWD 3, BACK 4, LEFT 2, RIGHT 2 of 23 selections). Before fixes: only BACK. `python -m pytest -q` -> 202 passed.
- Next step: camera view with YOLO boxes + gaze cursor + confirm (dwell now, SSVEP once EEG works). Rider setup: 50-70 cm from screen, light in front, head still, re-centre with C.

### Sat Nov 14, ~10:30 am - Claude Code (Opus 5.5), for Prakhar (gaze fallback, branch prakhar/gaze)
- Done: MediaPipe 1.2.3 installed with --no-deps (OpenCV untouched); face model in ~/hp26-models/face_landmarker/. `vision/gaze.py` (features, 9-point calibration fit, hysteresis, blink filter, gaze_step), `vision/gaze_tracker.py` (13 FPS on built-in camera), `vision/gaze_calibrate.py` (9 dots + 4-region accuracy), `app.py --gaze` (static arrows; same state machine + driver).
- Known bug: `app.py --gaze` launches the tracker with multiprocessing spawn, which re-imports app.py (pygame) in the child -> SDL clash -> 0 samples. Proven: launched from a pygame-free script it sends 77 samples / 8 s, face 76/77. Fix next: run tracker as its own program sending JSON over localhost UDP (INTERFACES.md transport rule).
- Evidence (command + result): `python -m pytest -q` -> all pass; mutation checks (blink limit 0 and 1 s, no hysteresis, stale gaze accepted) each fail a test.

### Sat Nov 14, ~2:00 am - Claude Code (Opus 5.5), for Prakhar
- Done: frequency assignment logic in `vision/detect_track.py`: `separate_targets` keeps only boxes with >= `MIN_GAP_FRAC` (5% of width) empty space from better-ranked boxes (overlap = rejected, next-best fills the slot); `assign_frequencies` keeps existing frequencies, gives a new box the free frequency furthest from its nearest neighbour's.
- Next step: render the actual flicker patches (interface/, pygame, separate process); tune MIN_GAP_FRAC in calibration.
- Known bugs: detect_fps 6-9 when Chrome uses ~86% CPU; close heavy tabs for demos.
- Evidence (command + result): `python -m pytest -q vision/tests` -> `36 passed`; live 30 s run -> `targets_now=2 labels=['chair']`.

### Sat Nov 14, 12:50 am - Claude Code (Opus 5.5), for Prakhar
- Done: `vision/destinations.py`: Gemini ranker (background thread, 1 frame every 4 s, JSON destinations with 0-1000 boxes) + `rank_targets` merge (Gemini-matched YOLO tracks first, Gemini-only targets like doors, then steadiest YOLO). `python -m vision.detect_track --gemini`. Installed `google-genai` 3.3.0 (needed for Gemini calls).
- In progress (file:function, state): LIVE. `gemini-2.5-flash` retired, 3.7/3.8-flash overloaded (503/504); fallback chain `GEMINI_MODELS` starts with `gemini-3.5-flash-lite` (1.1-2.7 s/answer, found a door). Live 40 s run: Gemini labels 'table with items 0.85', 'conference table' merged onto YOLO track #85 (~1.74 m); detect_fps=19.0. Dropped suggestions with score < 0.3. Sat ~1:30 am: new `SYSTEM_PROMPT` (rider context, score rubric, exclusions incl. portraits/stairs, box-size rule, label reuse) + API-enforced `RESPONSE_SCHEMA` + previous labels fed back; live: 'desk with laptop 0.90' then reused at 0.88; 33 tests pass. detect_fps fell to 9.1 in that run: check.
- Next step: live run; verify model name `gemini-2.5-flash` still served (override with GEMINI_MODEL).
- Known bugs: Gemini needs internet and sends room images to Google; advisory only, never in the control path.
- Evidence (command + result): `python -m pytest -q vision/tests` -> `31 passed`; `--gemini` without key -> logs the missing key and falls back to YOLO ranking.

### Sat Nov 14, 12:12 am - Claude Code (Opus 5.5), for Prakhar
- Done: `vision/detect_track.py`: YOLO11n + ByteTrack on the newest camera frame, 4 steadiest objects get a stable SSVEP frequency (`assign_frequencies`), an estimated distance from box height (`estimate_distance_m`, pinhole rule, NOT LiDAR, NOT a safety signal) and a steering offset; keys 1-4 select (stand-in for the decoder). Installed `lap` (ByteTrack needs it).
- In progress (file:function, state): LIVE on the Pixel (camera index 0; index 1 = built-in). `python -m vision.detect_track --source 0 --seconds 45` -> `summary: seconds=45.0 processed=885 detect_fps=19.7 tracks_seen=55 targets_now=2 labels=['bottle', 'laptop']`. Found laptop, cell phone, bowl, bottle, chair. IDs churned (55 IDs in 45 s) with a handheld phone; re-test mounted. Sat 12:25 am: added `RELEVANT_CLASSES` filter (`--all-classes` to disable) and distance/box-height in the log; `pytest -q vision/tests` -> 23 passed. Mounted re-run saw 0 objects because the Pixel feed was black (lens blocked or webcam paused).
- Next step: grant Camera to Cursor, run `python -m vision.detect_track --source 1`, calibrate `--hfov` with a person at 2.0 m. `TARGET_FREQS_HZ` is copied locally until `shared/protocol.py` exists (task 1.3).
- Known bugs: first YOLO call takes ~5 s (model load + Apple GPU warm-up). COCO has no "door" class.
- Evidence (command + result): `python -m pytest -q vision/tests` -> `22 passed in 1.44s`; `python -m vision.detect_track --source <ultralytics bus.jpg> --seconds 6` -> `targets: bus#1, person#3, person#2, person#4`.

### Fri Nov 13, 11:32 pm - Claude Code (Opus 5.5), for Prakhar
- Done: `vision/camera_source.py` (`LatestFrameReader`, `parse_source`, `redact_url`, `rolling_fps`, `SyntheticCapture`) and `vision/camera_view.py` (live window + FPS/frame-age overlay + exit summary). Same code opens Ring RTSP, webcam or file. Tests in `vision/tests/`.
- In progress (file:function, state): none. Ring bridge (ring-mqtt in Docker) not set up yet; human-run.
- Next step: Prakhar sets up ring-mqtt, runs `python -m vision.camera_view --seconds 60` on the Ring and records the summary line + glass-to-glass latency here. Vani: YOLO reuses `LatestFrameReader`.
- Known bugs: cv2 and pygame both bundle SDL2 (objc duplicate-class warnings); keep cv2 out of `interface/`. Ring needs internet and will likely lag 1-3 s; USB webcam is the fallback.
- Evidence (command + result): `python -m pytest -q vision/tests` -> `15 passed in 1.20s`; `python -m vision.camera_view --synthetic --seconds 5` -> `summary: seconds=5.0 frames=151 mean_fps=30.1 resolution=640x360 max_frame_age_ms=33 stalls=0 final_status=LIVE`.

### [time] - [model/agent]
- Done:
- In progress (file:function, state):
- Next step:
- Known bugs:
- Evidence (command + result):

## docs/ (owner: Prakhar)
### Sat Nov 14, ~7:15 PM - Claude Code (Fable 5.2), for Prakhar (how commands reach the hoverboard)
- Done: `docs/MOTOR_COMMANDS.md`: what the laptop sends to the ESP32 and the hoverboard boards and why (a power level per wheel, 20 times a second; no angle, time, distance or acceleration is ever sent), each stage from planner to motor, a worked example, all constants, the four stop layers, and a list of what is unverified.
- Needs a human: the unverified numbers in its section 7 (dead band 50, track width 0.55 m, real speed at 101 and 150, wheel signs); Keshav's newer bridge sketch is still on no branch.
- Evidence: written from `motors/driver.py`, `motors/bridge_protocol.py`, `control/navigation.py`, `control/goto.py`, `control/state_machine.py`, `firmware/bridge/bridge.ino` at 2b3a6cf; `python -m pytest -q` on that commit -> 555 passed, 1 failed (`test_flicker_runs_after_space`, passes alone: timing flake under load).

### Sat Nov 14, ~6:28 PM - Claude Code (Fable 5.2) with subagents, for Prakhar (independent audit, next steps, honest docs)
- Done: `docs/PROJECT_CONTEXT.md` (independent audit: how the whole project works, plus 14 findings with proof scripts). `docs/NEXT_STEPS.md` (ranked work for the hours left). Honesty pass over `DEVPOST.md`, `DEMO.md` (rewritten for the gaze + confirm + drive demo), `README.md`, `ARCHITECTURE.md`, `PRD.md`, `TEAMMATE_GUIDE.md`; `SAFETY.md` and `INTERFACES.md` only gained an "Implementation status" note, their rules are unchanged.
- Audit findings being fixed tonight (see the folder sections when they land): frozen camera keeps driving; arrival unreachable for chair/table/person; no operator stop in `object_select --drive`; obstacles limited to 4 on-screen boxes; no soft start; spin inside the motor dead band; jaw calibration accepts a dead signal.
- Needs a human: (1) the bridge sketch that PROGRESS describes (auto-detect, `hover_link.h`) is on no GitHub branch, and `firmware/README.md` says 4-pin plug while the debug log says 5-pin (its fifth pin carries about 14 V): Keshav / Pratosh please push the real sketch and fix the README. (2) The ultrasonic stop and kill switch have no test record. (3) `AGENTS.md` still describes the SSVEP design and `tools/smoke.py`, which does not exist (list of stale lines in the docs agent's report; humans own that file). (4) `DEVPOST.md` has 14 `[VERIFY]` markers to clear.
- Evidence: audit ran `python -m pytest -q` on a clean export of 1711282 -> `285 passed`; its proofs fake the camera, detector, tracker, headset and port (nothing ran on hardware).

### Fri Nov 13, 2:48 pm - Gemini 4 Carbon
- Done: Resolved all pre-kickoff audit issues across `docs/`, `AGENTS.md`, `motors/README.md`, `.cursor/plans/ssvep-chair.plan.md`, and `.cursor/rules/` (`20-bci.mdc`, `30-interface.mdc`, `50-motors.mdc`); added printable `docs/PHOTOSENSITIVITY_CARD.md`; installed `OpenBCI_GUI.app` (`v6.0.0-beta.1`), `ffmpeg` (`9.0.2`), `opencv-python-headless`, and offline YOLO weights (`yolov8n.pt`, `yolo11n.pt` in `~/hp26-models/`).
- In progress (file:function, state): none
- Next step: Confirm venue reply (0.1) and Keshav hardware answers (0.2), then create public GitHub repo at 8:00 pm sharp (Task 1.1).
- Known bugs: `cv2` wheel bundles `libSDL2` on macOS; mitigated via D3 (`vision/` runs in a separate process over UDP and `interface/` never imports `cv2` in Mode 1).
- Evidence (command + result): `(rg -n 'v <left>|d <cm>|TBD|D1-D5' docs/ || echo "no_stale_tokens_in_docs") && (rg -c '—' docs/*.md || echo "zero_em_dashes_in_docs") && ~/venvs/hp26/bin/python -c "import numpy, scipy, matplotlib, sklearn, brainflow, serial, pygame, pytest; print('mode1_imports_clean_zero_sdl_warnings')"` -> `no_stale_tokens_in_docs`, `zero_em_dashes_in_docs`, `mode1_imports_clean_zero_sdl_warnings`; `/Applications/OpenBCI_GUI.app`, `ffmpeg 9.0.2`, and `~/hp26-models/{yolov8n.pt,yolo11n.pt}` verified.

### Fri Nov 13, 10:48 am - Gemini 4 Carbon
- Done: Created `docs/TEAMMATE_GUIDE.md` covering clinical motivation, SSVEP + alpha mechanism, the 5 system parts, Mode 1 vs. Mode 2 gates, team folder ownership, Prakhar's weekend schedule, and the full Sunday 7:15 am Devpost/GitHub/video/judging checklist.
- In progress (file:function, state): none
- Next step: Complete Phase 0 prep items (venue reply, Keshav hardware confirmation, `~/venvs/hp26` import check) before 6:30 pm check-in.
- Known bugs: Pre-kickoff doc contradictions (`docs/QUESTIONS.md` and `docs/GLOSSARY.md` vs. `docs/INTERFACES.md` and `docs/SAFETY.md`) still need cleanup before Task 1.1 initial commit at 8:00 pm.
- Evidence (command + result): `wc -l "docs/TEAMMATE_GUIDE.md" && (rg -c '—' "docs/TEAMMATE_GUIDE.md" || echo "0 em dashes")` -> `190 docs/TEAMMATE_GUIDE.md`, `0 em dashes`.
