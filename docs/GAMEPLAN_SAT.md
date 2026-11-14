# Game plan (updated Sat Nov 14, 2:15 pm)

Fixed times: **Sat 6:00 pm go/no-go** (what we demo) | **Sun 1:00 am feature freeze** | **Devpost submitted Sun 7:15 am**
| Judging Sun 9:30 am. All code is on branch `prakhar/gaze` (includes Keshav's firmware); not in `main` yet.

## What we will demo (honest tiers)
| Tier | Demo | Needs |
| --- | --- | --- |
| **A (must)** | Rider **steers with their eyes**: look at an arrow -> 1.5 s dwell -> wheels move; look away / close eyes -> stop. Kill switch + ESP32 watchdog + ultrasonic stop shown. | gaze (works), app.py (works on mock), **ESP32 + hoverboard wired (open)** |
| **B (target)** | Rider **looks at a real object** (YOLO box turns yellow) and **clenches jaw to confirm** (green); chair turns toward it. | object_select (works, dwell confirm), jaw detector (practice passes), **EEG board connected (open)**, drive-to-object code (to do) |
| **C (stretch)** | Brain-signal (SSVEP) confirmation; Gemini picks likely destinations (doors, tables, people). | clean EEG signal (not yet); Gemini (works) |
Pitch it honestly: gaze = camera; jaw clench = muscle signal through the EEG headset; brain SSVEP = stretch.

## Status
| Piece | State | Evidence |
| --- | --- | --- |
| Safety state machine, motor driver, app.py | DONE (mock) | 231 tests; held key -> drive lines only after 1.5 s dwell |
| Gaze arrows (`app.py --gaze`) | WORKS live, needs polish | all 4 directions reached MOVING; calibration must be redone in the rider's seat |
| Gaze on objects (`vision/object_select.py`) | WORKS, accuracy improving | 3 confirmations, 0 false; now calibrates at session start; tracker IDs stable (4 vs 44-60) |
| Distance estimate | CALIBRATED for Pixel (85.5 deg) | chair at 1.55 m reads 1.55 m |
| Jaw-clench confirm (`bci/jaw.py`, `bci/jaw_live.py`) | READY, untested on a head | practice mode 4/4; guide `docs/JAW_CONFIRM.md` |
| EEG board | BLOCKED | Wi-Fi drops mid-session; last recording railed (ear clips) |
| Hoverboard -> ESP32 | BLOCKED | UART pins on the 4-pin plug not yet identified; `bridge.ino` not uploaded |
| Forward camera | FLAKY | Pixel drops webcam mode when it sleeps; iPhone Continuity Camera is the alternative |

## Who does what (now -> 6 pm)
**Hardware (Pratosh, Keshav)**
1. 4-pin plug: identify GND / VCC / TX / RX with the voltage method (board on, wheels up). Never wire VCC. 30 min
2. Wire ESP32 (left board GPIO17/18, right GPIO15/16), upload `firmware/bridge/bridge.ino`, run
   `python firmware/hoverboard/tools/bridge_bench_test.py /dev/cu.<esp32>`: wheels follow, last line WATCHDOG. 1 h
3. `python app.py --keyboard --serial /dev/cu.<esp32>` wheels up: hold Up -> 1.5 s -> forward; release -> stop. 30 min
4. Chassis: plank, casters, kill switch in the battery line, ultrasonic (TRIG GPIO4, ECHO GPIO5 via 1k/2k divider).
5. Mount the phone behind the laptop (clamp on the chair frame, camera forward, lid angle fixed).

**EEG (Vani + teammate)**: follow `docs/JAW_CONFIRM.md`
6. Prefer the USB dongle over Wi-Fi (battery + Auto-Join cause the drops). Fix railing (ear clips: SRB / BIAS bottom pins).
7. `python -m bci.jaw_live --dongle /dev/cu.usbserial-...`: 10 clenches -> 9-10 CONFIRM, 30 s talking -> 0. Record in PROGRESS.md.

**Prakhar (+ Claude)**
8. EyeTrax verdict: if better than ours, plug it in as the gaze source (same UDP message). 1 h
9. Confirmation source in object_select: SPACE now, jaw clench when the board works, dwell as fallback. 45 min
10. Drive-to-object: confirmed box -> turn until centred -> roll forward -> stop when close / lost / ultrasonic,
    through the same state machine, tested on the mock port, then wheels up. 2 h
11. Open the pull request `prakhar/gaze` -> `main`; Pratosh reviews control/motors, Vani reviews bci/vision.

## 6 pm go/no-go
- Tier A works wheels-up 3 times in a row -> evening = floor tests (permitted area, spotter, kill switch) + Tier B.
- Tier A does not work -> evening = fix the hardware chain only; demo gaze on screen with wheels on a stand.

## Evening and night
| Time | What |
| --- | --- |
| 7 pm - 1 am | integrate Tier B; film every first success on a phone; draft Devpost (problem, how it works, safety, honest limits) |
| 1 am | feature freeze; only demo-critical fixes after this |
| 1-2 am | film the final demo from two angles |
| 2-7 am | video edit (Prakhar after sleep), Devpost text, rehearse the 2-minute pitch twice |
| **7:15 am** | **submit Devpost** |

## Rules that do not change
STOP is the default. Humans run hardware; wheels off the ground first; kill switch in a hand; spotter for floor
tests. Ask every viewer about photosensitive epilepsy before any flicker. Calibrate gaze in the rider's seat.
