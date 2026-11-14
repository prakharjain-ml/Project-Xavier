# NEXT_STEPS: Sat Nov 14, 6 pm to Sun Nov 15, 8 am

Written from `PROGRESS.md`, `docs/GAMEPLAN_SAT.md`, `docs/ROUTE_REQUIREMENTS.md`, `docs/DEVPOST.md` and the code.
I did not run anything. "Proven" below means `PROGRESS.md` shows a command and its output. Everything else is a claim.

## 1. Where we stand (honest)

**Works on real hardware, per PROGRESS.md:** gaze on the Mac webcam picks the four arrows (all four reached MOVING in
one live run, `app.py --gaze --mock`); gaze picks real objects with YOLO and a dwell confirm (3 confirmations, 0
false, in `vision/object_select.py`); distance estimate reads 1.55 m at 1.55 m (one point, Pixel camera, 85.5 deg
calibrated); Gemini ranks destinations live; the LEFT hoverboard wheel runs end to end from the laptop through the
ESP32 (Keshav's handoff: forward, back, turn, watchdog stop). **Works only in simulation or on a mock port:** the
safety state machine, motor driver, `app.py`, the drive-to-object planner (`control/goto.py`, `control/navigation.py`
DWA, `object_select --drive --mock`), the A* path preview and HUD (`vision/nav_preview.py`, rendered from one live
frame, "sends nothing to any motor"), and the jaw detector (`bci/jaw.py`, only on synthetic clenches: 4 of 4).
**Does not work, or has no evidence:** the EEG board (last recording railed, Wi-Fi dropped); the jaw clench on a real
head (zero real clenches recorded); SSVEP (no usable signal, so drop it); the RIGHT wheel (slave board still being
unlocked); `bridge.ino` full dual-board run, ultrasonic stop and the 200 ms watchdog with both wheels on the real
chair (only the left wheel is shown); any floor drive, with or without a rider; camera height and tilt on the chair
(the HUD uses a 1.0 m and 15 deg guess); the route-preview rebuild (assume it lands tonight, but nothing is proven).
`PROGRESS.md` still says phase 0 and the team board is stale.

**The single biggest gap:** nobody has seen the chair move toward an object that a rider looked at, even once,
even wheels up. Everything upstream and downstream exists as two halves with a mock port in between.

## 2. The demo path

Smallest sequence a judge must see. "Proven" is judged strictly.

| # | Step | Proven? | Fallback on the day |
| --- | --- | --- | --- |
| 1 | Rider sits, laptop calibrates gaze (`object_select` does it at start, retry below 85%) | Yes, 97% on the arrows, per-session in objects | Press C to re-centre; re-run calibration; a teammate with a better-lit face rides |
| 2 | Forward camera sees objects with outlines or boxes, distances plausible | Partly (Pixel feed flaky, drops webcam mode when it sleeps) | iPhone Continuity Camera, or a USB webcam; keep the Pixel plugged in and screen-timeout off |
| 3 | Rider looks at an object, box turns yellow | Yes (live, 3 of 3) | Mouse stands in for the eyes (the route preview already does this) |
| 4 | Confirm: jaw clench turns it green | **No** (synthetic only) | Dwell (works) or SPACE/J key. Tell judges the truth: "dwell today, clench when the board is clean" |
| 5 | Chair turns and rolls toward the object | **No** (mock port only; right wheel unknown) | Wheels-up on a stand with the live screen, filmed; or left-wheel-only spin as a "turn toward" demo |
| 6 | Chair stops near the object, on obstacle, or on look-away | State machine yes (mock); ultrasonic and watchdog on the real chair no | Operator SPACE (E-STOP) and the hardware kill switch, both shown deliberately |
| 7 | Route preview on screen shows the planned path | Partly (one rendered frame) | Show it as "what the planner sees"; do not claim the chair follows that exact line (ROUTE_REQUIREMENTS says it does not yet) |

Rule for the day: if step 5 has not worked on the floor twice by 3 am, the demo is wheels on a stand plus the
filmed floor run. Say so on Devpost (the `[VERIFY: bench / loaded]` markers).

## 3. Ranked work items

Order is by "makes the demo certain or safe" first, then "makes it believable", then "pretty".
Hours are real hands-on hours. Owners follow `AGENTS.md`; agents never touch hardware.

| Rank | Item | Why | Folder, owner | Hrs | Risk | Verify | Depends on |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | **Both wheels on the chair, wheel signs set, battery power**: finish slave board (unlock, flash `e235_single_usart1.bin`, GPIO15/16, own solid GND), set `LEFT_SIGN`/`RIGHT_SIGN` in `firmware/bridge/bridge.ino`, run `firmware/hoverboard/tools/bridge_bench_test.py`. | No drive without it. Single largest unknown. | `firmware/`, Keshav + Pratosh | 2-3 | High (slave unlock took the left wheel most of a day) | Bench script: both wheels follow, last line WATCHDOG; film it. | Nothing. Start now. |
| 2 | **Safety pass on the real chain, wheels up, kill switch in hand**: (a) pull USB mid-drive, stop under 0.5 s; (b) hand in front of the ultrasonic, forward stops, a turn still works; (c) `python app.py --keyboard --serial <esp32>`: hold Up, 1.5 s, forward; release, stop; SPACE, E-STOP. Write numbers in PROGRESS.md. | The one thing that must be true before a person sits on it. Also the Devpost safety claims. | `motors/`, Pratosh; Prakhar watches | 1 | Low | Three videos plus a PROGRESS.md entry | Item 1 |
| 3 | **Camera and phone mount, then measure height and tilt**, pass `--cam-height` `--cam-pitch`. Lock the lid angle. Stop the Pixel from sleeping. | The distance estimate, the DWA goal and the floor ribbon all assume the camera geometry. Wrong height means the chair stops short or overshoots. A flaky camera kills the demo. | `vision/`, Vani (mount: Pratosh) | 1 | Medium | Put a chair at 1.0, 1.5, 2.0 m; log the three distance readings. Keep if within 15%. | Item 1 chassis done |
| 4 | **First drive-to-object, wheels up, then floor**: `object_select --drive --serial <esp32>` wheels up: look, dwell-confirm, wheels turn toward the object and stop at `ARRIVE_M`. Then floor, spotter, 3 m clear, minimum speed (`MAX_SPEED=150` cap, lower it first). Repeat to get 3 clean runs. | This is the demo. | `vision/object_select.py`, `control/goto.py`; Prakhar (design), Pratosh (integration, hands) | 3 | High: first time the planner meets real wheels, latency and slip | 3 of 3 runs end within about 0.5 m of the object, no uncommanded motion. Film every run. | Items 1, 2, 3 |
| 5 | **Dwell-confirm is the default, jaw is optional**: make sure the launch line for the demo is `--confirm dwell` and that jaw failure falls back to dwell without a restart. | Jaw is the least proven link. A demo that needs it is a demo that may not run. | `vision/object_select.py`, Prakhar | 0.5 | Low | Start with `--confirm jaw --jaw-board synthetic`, kill the jaw thread, confirm dwell still works. | None |
| 6 | **Jaw clench on a real head, 45 min time box**: dongle (not Wi-Fi), ear clips, `python -m bci.jaw_live --dongle ...`. Pass: 10 clenches gives 9-10 CONFIRM, 30 s talking gives 0, hold 5 s gives 1. If it fails twice, stop and use dwell. | It is the Healthcare and "Best Hardware" hook, and `DEVPOST.md` has three `[VERIFY]` lines waiting on its numbers. | `bci/`, Vani | 0.75-1.5 | High (board has not worked all weekend) | The three pass rows in `JAW_CONFIRM.md`, recorded in PROGRESS.md | Dongle plugged in |
| 7 | **Route-preview rebuild lands and is wired into the drive screen** (`vision/floor_route.py`, `scene_ai.py`, `hud.py`): show it inside `object_select --drive`. Keep C4 (no safe route, draw nothing). Test the Gemini-failure path: unplug Wi-Fi, screen must stay above 15 fps and show the dashed "unverified" route. | The judge's eye goes to this screen. It also shows the safety reasoning. | `vision/`, Prakhar (agents edit) | 2 | Medium | Run with the key removed and with Wi-Fi off; read fps from the overlay | Item 3 for correct geometry |
| 8 | **Devpost `[VERIFY]` sweep** (8 markers in `docs/DEVPOST.md`) using real numbers from items 1-6; delete any claim without evidence. | Submitting an unverified claim to judges hurts more than a smaller claim. | `docs/`, Prakhar | 1 | Low | `grep VERIFY docs/DEVPOST.md` returns nothing | Items 1-6 |
| 9 | **Demo video, two angles, plus a stand-only fallback video** filmed as soon as each step first works, not at 2 am. | A recorded floor run is the insurance against a dead battery or radio noise at 9:30 am. | all | 2 | Low | A file exists and plays | Items 2, 4 |
| 10 | **Update `DEMO.md` and `PROGRESS.md` team board** for the real pitch (it still describes SSVEP arrows and "phase 0"). | Judges and teammates will read it. Stale docs also mislead the next agent. | `docs/`, Prakhar | 0.5 | Low | Reading it matches section 2 above | Item 4 |
| 11 | **Open the PR `prakhar/gaze` into `main`**, reviewers named in GAMEPLAN item 11. | Submission repo must contain the working code, not just a feature branch. | repo, Prakhar | 0.5 | Merge conflicts with firmware branches | `git log main` shows the work | Item 8 first (docs) |
| 12 | **Sleep, in shifts**: at least 4 h for whoever drives or films. | Tired people press the wrong key near a moving chair. | all | 4-5 | n/a | n/a | n/a |

### Drop these now
- SSVEP, alpha-stop, the flicker screen (`interface/`), CCA/FFT decoder. No usable EEG, and gaze plus jaw replaced it. Mention SSVEP only as the original plan and future work.
- Mode 2 flickering YOLO boxes (the original definition). The shipped "Mode 2" is gaze-picked objects.
- Photon caregiver alert, calibration-free anything, new ML models, a rider seat or tray, polishing the HUD colours.
- Any new Gemini feature. It is advisory, 11.7 s on the first try, 3.7/3.8 models overloaded earlier. Keep it as a preview garnish.
- Do not claim SSVEP, "brain-controlled", or a rider-loaded floor drive anywhere unless it happened.

## 4. Improvements to what exists (cheapest change that helps)

| Feature | Problem seen in the repo | Cheapest change |
| --- | --- | --- |
| Gaze accuracy | Calibration must be redone in the rider's seat; accuracy changes with head movement; webcam about 13 FPS | Calibrate in the final chair with the final lid angle, as the last pre-demo step. Add a head rest or marked sitting distance (50-70 cm). Re-centre with C before each run. Keep `--skip-calibration` off. |
| Confirm reliability | Jaw untested; dwell is 1.5 s with a wobble reset | Keep dwell fallback; if gaze flickers off the object, look at the 2% enter / 8% exit margins in `update_selection` before touching anything else. |
| Obstacle handling | Camera obstacles are only objects YOLO knows (COCO classes filtered by `RELEVANT_CLASSES`); walls, glass, table edges are invisible to it. The ultrasonic is one forward sensor. | Clear the demo area of anything non-COCO. Say "demo in a cleared 3 m lane". Gemini no-go zones are a preview aid, not a safety layer (C7). Keep OBSTACLE_STOP_CM at 50; test it with a box, not only a hand. |
| Distance estimate | Pinhole-from-box-height, validated at one point; depends on object class height guesses | Run the three-distance check in item 3. If error is over 15%, scale stop distance conservatively (stop earlier). Never use it as a safety signal (it already is not). |
| Route preview | Draws a route the chair does not follow; height/tilt guessed | Label it "preview" on screen (HUD already has the mode string). Use measured height/tilt. Hide the route when there is no safe route (C4). |
| Screen | Status line and STOP button in the new HUD | Put one large line: "CONFIRMED: <label>, driving" and "STOPPED". Make STOP also a key (SPACE). Check it reads from 2 m in the room lighting. |
| Detection speed | `detect_fps` fell to 9 when Chrome was heavy; first YOLO call takes 5 s | Close Chrome; run one warm-up before judges arrive. |

## 5. Future work to mention to judges (do not build)
- Real SSVEP: when EEG contact is solved, flicker the object boxes (the original Mode 2). Name it as the path to a camera-free interface.
- Depth from a stereo or LiDAR sensor instead of box height; a wider ring of ultrasonic or ToF sensors.
- Speech or eye-blink as an extra confirm for riders who cannot clench.
- Clinical partners, a rider study, and a certified drive base. This is a prototype.
- A map of a home (known rooms and doors), so the rider picks "kitchen" rather than an object.

## 6. Cut line

| Real hours of work | Do exactly this |
| --- | --- |
| 2 h | Items 1 and 2 only, then film the wheels-up chain and show gaze on screen. Devpost says "bench". |
| 4 h | Add 3 and 5. First wheels-up drive-to-object using dwell. |
| 6 h | Add 4 (floor, spotter, minimum speed) and 9 (film it). This is the real target. |
| 8 h | Add 8, 10, 11. Then 6 (jaw) as a time-boxed bonus. |
| 10 h or more | Add 7 and polish the screen. Rehearse the pitch twice with the judge interruptions in `DEMO.md`. |

Hard stops: **1:00 am** feature freeze (already in GAMEPLAN); **7:15 am** submit Devpost. If item 1 is not done by
**10 pm**, switch to the stand-only demo and spend the remaining time on items 3, 7, 8 and 9. Never trade a safety
check (item 2) for a feature.
