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
