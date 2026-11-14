# Saturday Nov 14 game plan

Built from `.cursor/plans/ssvep-chair.plan.md` (phases 2-5) and the state of the repo at ~3 am. Owner: Prakhar.
The two times that never move: **Sat 6:00 pm Mode 2 go/no-go** and **Devpost submitted Sun 7:15 am**.

## Where we are (3 am)
| Piece | Status | Evidence |
| --- | --- | --- |
| `shared/protocol.py` (task 1.3) | DONE | 23 tests; constants parsed from INTERFACES.md |
| `control/state_machine.py` (2.11) | DONE, needs Pratosh review | 53 tests, one per SAFETY.md row, fuzz, mutation-checked |
| `interface/flicker.py` (2.6-2.8) | CODE DONE, timing NOT verified | 14 headless tests; needs a human 60 s run on the MacBook screen |
| `vision/` (Mode 2 head start) | WORKING on webcam | YOLO + ByteTrack + Gemini ranking, 36 tests |
| `tools/smoke.py` (1.7, Vani) | NOT STARTED | Gate 1 cannot pass without it |
| `bci/` (Vani) | UNKNOWN | check PROGRESS.md bci section |
| Hardware: firmware flash, bridge, chassis (2.13-2.16) | UNKNOWN | Keshav and Pratosh worked overnight |
| Real SSVEP peak on a head (2.10) | UNKNOWN | OpenBCI data flows; a 12 Hz peak has not been recorded here |
| Venue permission to ride, Keshav CONFIRM list | UNKNOWN | paste answers into PROGRESS.md |

## First 30 minutes after waking (Prakhar)
1. Share the overnight work (it is on a local branch nobody else can see yet):
   `git push -u origin prakhar/overnight-mode1`, then on GitHub click "Compare & pull request" into `main` and ask
   Pratosh to review `control/state_machine.py`. Then `git checkout main && git pull` after merge, and read
   PROGRESS.md (bci, motors/firmware sections) to fill in the UNKNOWN rows above.
2. Flicker timing gate (2.6): `python -m interface.flicker --seconds 60` fullscreen, everything else closed
   (Chrome used ~86% CPU last night). Pass = `mean_fps` 59.5-60.5 AND `dropped=0` AND no red
   "NO VSYNC" text / "vsync is not pacing" log line. Paste the summary line into PROGRESS.md.
   Do this BEFORE electrodes go on: Prakhar is the default rider for 3.2 at 6:45, and a bad flicker means bad
   calibration data.
3. Dwell bars (2.8): `python -m interface.flicker --fake-status` for 20 s; bars fill, FPS stays 60.
4. Phone check (2.9): 240 fps video of `python -m interface.flicker --single 12`, count frames per cycle (expect 20 phone
   frames per 12 Hz cycle); repeat for 6.67, 8.57 and 15. Pass = within 2%.

## Schedule
| Time | Phase | Who | Done when (gate) |
| --- | --- | --- | --- |
| 6:00-6:45 | 3.1 `tools/record.py` | Vani | one labeled file per session in `data/raw/` |
| 6:00-6:45 | flicker gates above (2.6, 2.8, 2.9), before electrodes | Prakhar | 59.5-60.5 FPS, `dropped=0`, frequencies within 2% |
| 6:45-7:45 | 3.2 record two sessions (4 targets, eyes closed, rest) | rider + Vani | two sessions saved |
| 7:45-9:00 | 3.3 `tools/analyze.py`: FFT vs CCA, windows 1.0/1.5/2.0 s | Vani | table in `docs/calibration.md` |
| 9:00-9:30 | 3.4 choose frequencies, window, threshold | Prakhar + Vani | update INTERFACES.md first, then protocol.py (test enforces it) |
| 9:30-10:45 | 3.5 live screen-only test, 3.6 alpha stop test | Prakhar | >= 80% accuracy, < 4 s to select, rest -> NONE >= 90%, alpha 5/5 with 0 false stops |
| 10:45-11:00 | 3.7 record 60 s of live decoding for the video | Vani | clip saved |
| **11:00** | **Gate 3 + sync** | all | numbers in PROGRESS.md; else take the fallback ladder (3 targets, 2 targets, 2 s window) |
| 11:00-12:00 | 4.1 `app.py`: decoder -> `control.state_machine.step` at 20 Hz -> mock motors | Vani + Prakhar | runs with `--synthetic --mock` |
| 10:30-12:00 | 4.0 mount ESP32, ultrasonic, kill switch; teleop, wheels off ground | Pratosh + Keshav | drives and stops through the bridge |
| 1:00-2:00 | 4.2 wheels-off test with full app and real rider | Pratosh + Keshav | video: wheels follow gaze, stop on look-away and eyes closed |
| 2:00-3:00 | 4.3 first floor test, minimum speed, spotter + kill switch | all | drives forward and stops correctly |
| 3:00-4:30 | 4.4 tune dwell, speed cap, turn speed | Pratosh + Prakhar | constants changed in INTERFACES.md with a reason |
| 4:30-5:00 | 4.5 ultrasonic stop 5/5 | Keshav | video |
| 5:00-6:00 | 4.6 full section 1.3 demo three times in a row | all | three passes recorded |
| **6:00 pm** | **Go/no-go** | all | pass -> 5A (Mode 2); fail -> 5B (hardening). Not extended. |
| 7:00 pm-1:00 am | 5A: vision -> interface boxes -> GoalHint -> control | Vani, Prakhar, Pratosh | chair reaches a chosen object 2 of 3 tries |

## Decisions waiting for the 11 am sync
1. Confirm the two state-machine readings in PROGRESS.md (stale data never clears E_STOP; alpha keeps sending
   StopRequest while eyes are closed).
2. Confirm the `GoalHint` contract added to INTERFACES.md.
3. Alpha-band overlap: 8.57 and 12 Hz sit inside 8-13 Hz. If task 3.6 shows false stops, the best valid set
   outside the band is 5, 6.67, 15, 20 Hz (all 60/n, no frequency double another, >= 1.67 Hz apart). Costs:
   5 Hz is tiring to watch; 20 Hz gives a weaker SSVEP and is in the most photosensitive range. Let the
   calibration data decide. (Do NOT use 7.5 with 15 Hz: 15 = 2 x 7.5.)

## Mode 2 work already done (only used if the 6 pm gate passes)
`python -m vision.detect_track --source 0 --gemini`: wheelchair-relevant objects only, stable IDs, flicker
frequencies kept per object and spread apart between neighbours, overlapping boxes rejected, distance estimate,
Gemini picks likely destinations (doors, tables with items, people). Remaining for 5A: send TargetSet/GoalHint
over UDP, draw flickering boxes in `interface/`, map the winning frequency to a target in `control/`.

## Never forget
- Default command is STOP. Humans run hardware. Wheels off the ground before anyone rides.
- Ask every viewer about photosensitive epilepsy before the flicker starts.
- Film every first success on a phone (footage for the 2-minute video).
- Nobody tests motors without sleep.
