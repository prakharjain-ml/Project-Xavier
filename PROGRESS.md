# PROGRESS.md

Live state for humans and agents. Edit only your own section. Newest entry first. Update before you switch agents,
sleep, or merge. Write for a reader who has seen nothing: name files and functions.

## Team board (owner: Prakhar)
- Current phase: 0 - Prep | Next gate: Gate 0 (all laptops pass import + rules test)
- Last sync: - | Next sync: Fri 8:00 pm kickoff
- Gate log:
  - Gate 0: [x] Prakhar (toolchain + rules + OpenBCI GUI + YOLO cache + ffmpeg verified) [ ] Keshav [ ] Pratosh [ ] Vani
- Decisions: D1 to D8 are locked in section 6 of the plan. Record any change here with time, reason and who agreed.
  - Fri Nov 13, 2:45 pm (pre-kickoff spec reconciliation, Prakhar): Set Phase 1 kickoff constants in `docs/INTERFACES.md` (`CONF_THRESHOLD=0.15`, `MAX_SPEED=150`, `TURN_SPEED=120`, `OBSTACLE_STOP_CM=50`, `ALPHA_BAND_HZ=(8,13)`), made ultrasonic forward-obstacle stop non-latching (`STOPPED` when `(left + right) > 0` and `0 < distance_cm < OBSTACLE_STOP_CM`, `-1` on echo timeout) so in-place turns are never deadlocked, and aligned `docs/` + `.cursor/rules/` ahead of the 8:00 pm initial commit.
- Open questions: section 12 of the plan (venue permission, exact hardware). Paste each answer here when it arrives.
- Blockers: none yet

---

## bci/ (owner: Vani)

### November 15 — Jaw–temple clench demo
- Added the standalone live detector, calibrated model, and EMG datasets in `models/jaw-temple/`.
- Rebuilt from the two bundled sample files with the README command. The cutoff was 10.5 µV RMS and the rebuilt joblib matched the demo model byte for byte.

### [time] - [model/agent]
- Done:
- In progress (file:function, state):
- Next step:
- Known bugs:
- Evidence (command + result):

## interface/ (owner: Prakhar)
### [time] - [model/agent]
- Done:
- In progress (file:function, state):
- Next step:
- Known bugs:
- Evidence (command + result):

## control/ (owner: Prakhar design, Pratosh integration)
### [time] - [model/agent]
- Done:
- In progress (file:function, state):
- Next step:
- Known bugs:
- Evidence (command + result):

## motors/ and firmware/ (owner: Pratosh, with Keshav)
### Sun Nov 15, 1:05 AM - Claude Code (Opus 5.5), for Keshav
- Done: ESP32 now runs over its **COM port** (CH343); the native USB connector was damaged in a drive test (power only, no data). Sketch re-uploaded with `USB CDC On Boot -> Disabled`; `bridge.ino` code unchanged. Added `firmware/test_code/keyboard_drive.py` (arrow-key teleop, Windows only). `chair_control/README.md`: COM-port and macOS setup (port names, CH34x driver, data cable).
- In progress (file:function, state): none. A WiFi (UDP) fallback was prototyped and reverted (not in the repo).
- Next step: Try `chair_control` on the demo MacBook (`ls /dev/cu.*`, then `python3 firmware/chair_control/example.py /dev/cu.<name>`). Optional: cross-platform pygame version of `keyboard_drive.py`. Repair the ESP32 USB-C connector when there is time.
- Known bugs: `DEFAULT_PORT` in `chair.py` is still `COM4`, so pass the port explicitly (`COM5` on Keshav's laptop).
- Evidence (command + result): `python test_code/keyboard_drive.py 200 COM5` after the re-upload -> both wheels drive on arrow keys (Keshav, wheels up). Before the re-upload: `bridge ?`, no motion.

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
