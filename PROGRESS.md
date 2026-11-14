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
  - Sat Nov 14, ~3:00 am (Prakhar, via Claude Code; CONFIRM at 11 am sync): added `GoalHint` (vision -> control, Mode 2) and the JSON-over-UDP transport rule (`"v"` + `"type"`, invalid messages dropped) to `docs/INTERFACES.md`; `shared/protocol.py` updated with a doc-parity test. Reason: vision must never send wheel speeds, so a hoverboard or firmware change only touches `motors/` and `firmware/`.
- Open questions: section 12 of the plan (venue permission, exact hardware). Paste each answer here when it arrives.
- Blockers: none yet

---

## bci/ (owner: Vani)
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
- Next step (HUMAN, on the MacBook screen): `python -m interface.flicker --seconds 60` -> need `dropped=0`; `python -m interface.flicker --fake-status`; then 240 fps phone video per target (2.9). Headless tests prove logic only, not timing.
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
### [time] - [model/agent]
- Done:
- In progress (file:function, state):
- Next step:
- Known bugs:
- Evidence (command + result):

## vision/ (owner: Vani)
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
