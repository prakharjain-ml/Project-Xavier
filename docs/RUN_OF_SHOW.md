# RUN_OF_SHOW: Sat Nov 14, 7 pm to Sun Nov 15, 10 am

Written Sat 7 pm. Owner: Prakhar. Roles follow `AGENTS.md`: Vani (rider, headset, `bci/`, `vision/`), Pratosh
(`motors/`, integration, hands on the chair), Keshav (`firmware/`, hoverboard, kill switch), Prakhar (`control/`,
`interface/`, `docs/`, coordinator, Devpost, video edit). Video plan: `docs/VIDEO_SCRIPT.md`. Older plans
(`docs/NEXT_STEPS.md`, `docs/GAMEPLAN_SAT.md`) say the same things in other words; where times differ, this file wins.

## Facts this plan depends on
- Proven on hardware: only the left wheel. The right wheel board is not finished.
- Proven live with a mock motor port: gaze picks arrows (11 of 23 held to moving), gaze dwell confirms objects.
- On screen only: the route preview. The chair does not drive along it. Route-following is being built tonight.
- Never seen: the chair driving to an object a rider looked at, even wheels up. The jaw clench from a real head.
- Landed tonight, untested on hardware: SPACE stop, frozen-camera stop, soft start, arrival detection.
- Venue rules for floor runs and where we stand for judging are not in the repo. [VERIFY: Prakhar asks an organizer on Discord or in person tonight: may we run a powered chair indoors, and where.] Judging is 9:30 am to 2:30 pm per `docs/TEAMMATE_GUIDE.md`. The 10:00 am demo time comes from the team. [VERIFY: Prakhar checks Discord at 8:00 am for the assigned spot and slot.]
- The team's plan caps each live judge visit at 2 minutes (`docs/TEAMMATE_GUIDE.md` section 6). The 5-minute script below has a 2-minute cut marked. [VERIFY: Prakhar asks whether our 10:00 am slot is 2 or 5 minutes.]

## The three decisions the team makes tonight
| # | When | Decision | Who decides |
| --- | --- | --- | --- |
| D1 | 8:15 pm | Is the jaw clench the confirm in the video and the demo, or is dwell the confirm? | Vani proposes from her test numbers; Prakhar confirms |
| D2 | 10:00 pm | Both wheels go or no-go. No-go means the stand-only demo plus filmed footage. | Keshav and Pratosh report; Prakhar calls it |
| D3 | 12:00 am | Does anything run on the floor, and does anyone sit on the chair? Default: no floor run and nobody on the chair. | All four; any one person can veto |

Rule behind all three: a "no" is not a failure. It sets which fallback in `docs/VIDEO_SCRIPT.md` and in the live script
is used. Whoever says no first is right until the others show a measurement.

## Hour by hour
Times are targets. If a block overruns, cut the next optional block, not the sleep block and not the safety pass.

| Time | Prakhar | Vani | Pratosh | Keshav |
| --- | --- | --- | --- | --- |
| 7:00-7:15 pm | 10 min huddle: read this file, name owners, ask the organizer about floor runs | huddle | huddle | huddle |
| 7:15-8:15 pm | Film screen-only shots 1, 2, 3, 4B, 5 (`docs/VIDEO_SCRIPT.md`), himself as rider for the screen shots. Gaze must hold in his own seat. | Jaw test, time-boxed (next section). | Right wheel with Keshav, then wheel signs | Right wheel (slave board): unlock, flash `e235_single_usart1.bin`, GPIO15/16, own solid GND |
| 8:15 pm | D1 | Reports jaw numbers | | |
| 8:15-10:00 pm | Merge route-following work only if it has tests passing. Update `PROGRESS.md` board (it still says Phase 0). Start clearing `[VERIFY]` markers that need no hardware (table below). | Review shots filmed so far; if D1 is "jaw", practise 3 clean clenches on camera; else practise the dwell rider script | Both wheels on the bench: `python firmware/hoverboard/tools/bridge_bench_test.py PORT`; set `LEFT_SIGN` and `RIGHT_SIGN` in `firmware/bridge/bridge.ino`; run on the battery, not the charger | same |
| 10:00 pm | D2: both wheels go or no-go | | reports | reports |
| 10:00-11:00 pm | Watches the safety pass, logs numbers in `PROGRESS.md` | Films the safety pass (shot 7, 6B) | Wheels-up safety pass (section below) | Hand on the kill switch for every powered step |
| 11:00-11:45 pm | If GO: first wheels-up drive-to-object, `object_select --drive --serial PORT --confirm dwell`. If NO-GO: shot 6B bench with the left wheel, three clean takes. | Rider for the wheels-up run | Hands, SPACE | Kill switch |
| 11:30 pm | Code freeze for anything that changes a motor command. A change after this needs a new wheels-up pass before it is filmed or shown. | | | |
| 12:00 am | D3 | | | |
| 12:00-1:00 am | Film the final shots that earned a place (video shot list), then `PROGRESS.md` entry | Rider or on camera | Drives | Kill switch |
| 1:00-1:30 am | Rough "safe cut" using fallbacks and whatever else was filmed; upload unlisted to YouTube as insurance | Writes her `[VERIFY]` numbers into `PROGRESS.md` | Writes his | Writes his |
| 1:30 am | Everyone off the hardware. Battery off, kill switch off, kept apart from the laptop. Charge only while someone is awake and watching. | | | |
| 1:30-5:30 am | SLEEP (until 5:30) | SLEEP | SLEEP | SLEEP |
| 5:30-6:30 am | Final cut, swap in any primary shots that earned it, voice-over, export, upload unlisted | Final read of the Devpost text for claims the repo does not back | Charge or check the battery while awake [VERIFY: Keshav reads pack voltage] | Same |
| 6:30-7:15 am | Apply markers to `docs/DEVPOST.md`, paste into Devpost, add video link, public repo link | Check the repo is public and the README is current | Check `main` has the final code (merge `prakhar/gaze`), tag it | Each adds Discord username |
| 7:15 am | SUBMIT (internal deadline) | | | |
| 7:15-8:00 am | Submission buffer. Only fix errors the form shows. Official hard deadline is 8:00 am (the packet says 8:00 am; the schedule PDF says 8:15 am). Do not use the buffer for features. | | | |
| 8:00-8:30 am | Check Discord for the assigned spot | Breakfast, pack the headset | Pack and check cables | Pack the chair, charge status |
| 8:30-9:00 am | Move to the judging spot, set up | Set up laptop, camera and headset | Set up chair, stand | Kill switch, floor, tape |
| 9:00-9:30 am | Rehearsal of the live script, once with a timer (section below). Also run both laptops' programs once. | Rider | Spotter | Operator |
| 9:30-9:55 am | Pre-demo check (section below) | | | |
| 10:00 am | LIVE DEMO | | | |

Sleep blocks: all four 1:30-5:30 am. If a hardware problem is still open at 1:30 am, one person (named at the 12:00 am
huddle) may stay up until 3:00 am and sleep 3:00-6:00 am. Nobody touches powered hardware after 3:00 am without a second
awake person. Tired people press the wrong key near a moving chair.

## Jaw test on a real head (Vani, 7:15-8:15 pm, 45 minutes hard stop at 8:15)
Goal: to know, once, whether the clench is read from a real head. The steps and the pass rows are in `docs/JAW_CONFIRM.md`.
1. USB dongle, not the Wi-Fi shield. Ear clips on the bottom pins (SRB, BIAS). Check the board is not railed.
2. Find the port: `ls /dev/cu.usbserial-*`. The dongle is a `usbserial-DM...` port. It is never given to `--serial`.
3. `python -m bci.jaw_live --dongle /dev/cu.usbserial-XXXX --channels 1 --seconds 60`
4. Pass rows (from `docs/JAW_CONFIRM.md`): 10 clenches gives 9 or 10 CONFIRMs; 30 s of talking gives 0; one 5 s hold gives 1.
   Talking matters more than the others: the presenter talks during the demo.
5. If it fails twice, stop at once, the answer is D1 = dwell. Do not spend more time.
6. If it passes: run `python -m vision.object_select --confirm jaw --jaw-port /dev/cu.usbserial-XXXX --jaw-channels 1`
   once with no `--drive`, three picks. Write the ratio line, the CONFIRM count and the false count into `PROGRESS.md`.
7. Known risk: strong mains hum from a detached electrode can look like a clench (`PROGRESS.md`, bci section). If the clench
   fires when nobody clenches, that is a fail.

D1 outcome: PASS gives "jaw" in the demo, with dwell as the fallback if a confirm does not fire twice in a row. FAIL gives
"dwell" and the video shot 4 fallback B.

## Go/no-go for both wheels (10:00 pm)
GO needs all of these, with a person saying "yes, I saw it":
1. Both wheels follow `bridge_bench_test.py` forward, backward and in a turn, wheels off the ground, on the battery.
2. The last line of the bench test is the watchdog stop (laptop silent gives zero).
3. Wheel signs set: forward is forward on both sides, a turn is a turn.
4. Keshav has a hand on a kill switch that cuts motor power. [VERIFY: Keshav says where it is fitted; `docs/SAFETY.md` says no record that it is.]
NO-GO (any one is missing) means: the demo becomes the stand-only demo.
- Stand-only demo: left wheel only (or both if later fixed), chair on a stand, wheels off the ground. The live demo shows gaze on screen, the route preview, then `python app.py --keyboard --serial PORT` (or `object_select --drive` if it passed wheels-up) on the stand.
- The video uses the fallback shots (6B for shot 6). The Devpost says "bench", "left wheel only" and "the right wheel is not done". The Best Physical AI track is not claimed.
- Keshav and Pratosh keep working on the right wheel until 12:00 am only if the left-wheel safety pass is already done. Otherwise stop and do the safety pass.
- After 12:00 am no more wheel-board work. Sleep.

## Wheels-up safety pass (before any floor run, and before any rider; Pratosh runs it)
Do this for whichever wheels are working. It is also the footage for video shot 7. Wheels off the ground, kill switch in
Keshav's hand, minimum speed. Any uncommanded motion: stop, log it in `PROGRESS.md`, fix, repeat from step 1.
1. `python app.py --keyboard --serial PORT`: hold Up. Watch the dwell bar and the 1.5 s wait, then the wheel ramps up (soft start). Release: it stops. Write what you saw.
2. SPACE while the wheel turns: it stops and the screen shows E-STOP. Press an arrow: no motion. Press R, then hold Up again: it waits 1.5 s again. 
3. Kill switch while the wheel turns: power dies. Turn it back on; nothing moves by itself.
4. Pull the USB cable mid-drive. Time the stop with a phone filming at its highest frame rate, counting frames from the pull to the stop. `docs/SAFETY.md` says the cable pull is likely a 500 ms stop on the boards, not 200 ms. [VERIFY: Pratosh writes the measured time and the frame rate used.]
5. Laptop hang: with the wheel turning, stop the Python program with Ctrl+C or suspend it. The ESP32 watchdog should zero the wheels. [VERIFY: Pratosh writes the measured time.]
6. Hand or a box in front of the ultrasonic sensor with the wheel going forward: forward stops, a turn still works. If the sensor is not fitted, write "not fitted" and do not mention it in the video or the demo.
7. Frozen forward camera, for the object program: `python -m vision.object_select --drive --serial PORT --confirm dwell`; confirm an object so the wheels turn, then unplug the phone camera. The chair should stop within about half a second (STALE_INTENT_S is 0.5 s in `shared/protocol.py`). [VERIFY: Pratosh writes what happened.] 
8. Write a `PROGRESS.md` entry in the `motors/` section with every number and every "did not happen".
If steps 1 to 3 fail, nothing powered goes further tonight: D2 and D3 are "no".

## Floor run gate (D3 at 12:00 am)
All of these, else no floor run and nobody on the chair:
1. Safety pass done and written in `PROGRESS.md`.
2. Venue allows it [VERIFY: Prakhar's answer from the organizer].
3. The first wheels-up drive-to-object run (11:00 pm) worked twice in a row.
4. At least 3 m of clear floor and nothing the camera cannot see in the lane (the detector knows chairs, people and some objects; it does not know glass, walls or table edges).
5. A spotter walking beside the chair, kill switch in hand, minimum speed (`MAX_SPEED` cap lowered first).
First floor run is with nobody on the chair. A rider only if all four agree in D3, one person has a hand on the kill switch and a
second on SPACE, and the floor run has already gone clean three times unloaded. Never a judge, never a stranger
(`docs/SAFETY.md`).
Camera height and tilt: [VERIFY: Pratosh or Vani measures the phone's height in metres and tilt in degrees on the chair and passes `--cam-height` and `--cam-pitch`]. The defaults are guesses (0.89 m, level). Wrong values make the chair stop short or overshoot.
If a floor run gives anything odd (stops short, drifts, overshoots), the demo stays on the stand. Write it in `PROGRESS.md`.

## Clearing the `[VERIFY]` markers in `docs/DEVPOST.md`
Each owner writes the number and how it was measured into `PROGRESS.md` by 1:30 am. Prakhar applies it to
`docs/DEVPOST.md` at 6:30 am. A marker with no evidence is deleted along with the claim next to it, not softened.
`grep VERIFY docs/DEVPOST.md` must print nothing before submitting.

| Marker (in DEVPOST.md) | Owner | Evidence |
| --- | --- | --- |
| Discord usernames, all four | each teammate | typed by each person |
| Elevator pitch: jaw clench read from a real head | Vani | `jaw_live` numbers from the 8:15 pm test, or delete the clause |
| Step 3: stop time after the gaze leaves | Pratosh, with Prakhar | measured at the wheels on the chair, or delete the number. No measurement exists today. |
| Step 4: keep only if the clench works and drive-to-object ran on the real chair | Vani (clench), Prakhar (drive) | the 8:15 pm test; the 11:00 pm run in `PROGRESS.md` |
| Rider, stand, or bench | Prakhar after D3 | what was filmed and shown |
| State machine rate in object mode | Prakhar | log the loop rate in an `object_select --drive` run, or delete the sentence |
| Watchdog stop time (laptop hung, USB pulled) | Pratosh | safety pass steps 4 and 5 |
| Hours the hoverboard was dead; when the left wheel first worked; right wheel | Keshav | his own clock |
| Headset signal state, and what fixed it | Vani | a fresh recording or the 8:15 pm result |
| Accomplishment 3, the clench numbers | Vani | `jaw_live` ratio line, CONFIRM count, false count while talking |
| Accomplishments: both wheels, loaded or bench | Keshav | D2 and D3 outcomes |
| One lesson per teammate | each teammate | their words, one sentence |
| Gemini in Built with | Prakhar | keep only if the demo or the video ran `--scene-ai gemini` |
| Track: Best Physical AI | Prakhar | claim it only if the chair drove itself to a chosen object in the live demo or a recorded floor run. Otherwise leave it unchecked. |
| Submit time line in DEVPOST.md says 7:45 am | Prakhar | change it to 7:15 am, the internal time |

## Pre-demo check (9:30-9:55 am), in this order
1. Photosensitivity: the object demo does not flicker, so no warning is needed for it. If the flicker screen is not shown, do not run `interface.flicker`.
2. Charge: battery voltage read by Keshav [VERIFY]. Battery off until the chair is on its stand or in its lane.
3. Both cameras: `python -m vision.object_select --seconds 60` with no `--drive`. Gaze calibrated in the rider's seat, last thing. Phone camera plugged in, screen timeout off, nothing else heavy running (close Chrome; the first detector call takes seconds, so warm it up now).
4. Port: `ls /dev/cu.*`. The ESP32 is not a `usbserial-DM...` port (that is the OpenBCI dongle). Pratosh writes the port name on tape on the laptop.
5. Wheels-up check: `python app.py --keyboard --serial PORT`, hold Up, release, SPACE, R. Operator confirms the kill switch cuts power.
6. Lane (if floor): 3 m clear, tape marks, one object at the end.
7. `PROGRESS.md` is committed so the repo shows what was true today.

## Live demo script for judges (5 minutes)
Roles:
- Rider: Vani. Wears the headset if D1 is "jaw". Looks at objects. Never leaves the seat during a run.
- Operator: Keshav. One hand on the battery kill switch. The other hand on the laptop's SPACE key if the laptop is in reach of the chair. [VERIFY: Pratosh and Keshav check at 9:00 am that one person can reach both. If not, Pratosh holds SPACE and Keshav holds only the kill switch.]
- Presenter: Prakhar. Talks, narrates, answers questions, watches the screen. Does not touch the keyboard during a run.
- Pratosh: spotter and keyboard. Starts each program, watches the floor and the wires.

Before judges arrive: the chair is on its stand (or in its lane if D3 allowed it), the battery is off, the kill switch is in
Keshav's hand. Calibration is done. Terminal windows are open, one per command, already in the repo with the venv.
Any judge who asks to try it is offered the screen-only part (`object_select` with nothing driving), not the chair.

| Time | Who | What is said or done | Command |
| --- | --- | --- | --- |
| 0:00-0:30 | Prakhar | "Some people can't use a joystick. We built a prototype where the rider looks at an object, confirms, and the chair goes toward it. I'll show what works today and say what doesn't." | none |
| 0:30-1:00 | Prakhar | Walk the hardware in 30 s: laptop webcam, phone camera, headset, ESP32 safety bridge with its 200 ms watchdog, hoverboard motors, kill switch. Say the default command is stop. | none |
| 1:00-2:00 | Vani, Prakhar | Gaze on screen, nothing driving. Vani looks at an object, the outline gets a ring, after 1.5 s it is chosen. Say: "Nothing drives in this part." | `python -m vision.object_select` |
| 2:00-2:30 | Prakhar | Route preview. "The mouse stands in for the eyes here. It draws the route we plan on the floor. The chair does not follow this line yet." Close it with Q. | `python -m vision.nav_preview --scene-ai off` |
| 2:30-3:45 | Pratosh starts; Vani rides; Keshav operator | The chair. Two versions, chosen at 9:30 am by what passed:<br>**A (only if the wheels-up drive-to-object run worked twice):** `object_select --drive` on the stand. Vani looks, confirms, the wheels turn toward it. Say "wheels off the ground".<br>**B (default):** the bench. `app.py --keyboard`: Pratosh holds Up, the dwell bar fills over 1.5 s, the wheel turns, he lets go and it stops. Say "left wheel only, keyboard stands in for the rider" (and "both wheels" only if D2 was a go). | A: `python -m vision.object_select --drive --serial PORT --confirm dwell`<br>B: `python app.py --keyboard --serial PORT` |
| 3:45-4:15 | Keshav | Stops, on purpose: SPACE while the wheel turns (screen shows E-STOP), press R to re-arm, then turn the kill switch. Presenter says only what the operator did. | SPACE, R, kill switch |
| 4:15-4:30 | Vani, if D1 is "jaw" | Clench to confirm once. Say what the numbers are, only the ones in `PROGRESS.md`. If D1 is "dwell": skip. | `python -m vision.object_select --confirm jaw --jaw-port PORT --jaw-channels 1` |
| 4:30-5:00 | Prakhar | What is not done: right wheel, driving to an object on the floor, jaw clench on more than one person (only list what is still true). What is next: test with people who use power wheelchairs. Ask for questions. | none |

2-minute cut (if the slot is 2 minutes): 0:00-0:20 problem and one-line hardware; 0:20-1:00 gaze on screen; 1:00-1:40 the
chair (A or B) with one SPACE stop; 1:40-2:00 what is not done. Skip the route preview and the jaw unless they are the
strongest thing that worked.

### Numbers allowed in the pitch
Only these, unless `PROGRESS.md` has more by then: 1.5 s dwell; the ESP32 watchdog is set to 200 ms; 11 of 23 arrow
selections held to moving (on a test port); gaze dwell gave 3 confirmations and 0 false (`docs/GAMEPLAN_SAT.md`); clench
numbers from the 8:15 pm test; stop times from the safety pass. Never: "brain-controlled", "SSVEP works", "drives to
objects" (unless 6A or a floor run happened), a stop time we did not measure.

### Questions to expect (answers use only what we have shown)
- "Is that a brain signal?" The clench is muscle read by the headset. We planned a brain signal (SSVEP). Our first recording had no usable peak, so we switched to gaze and a clench.
- "How accurate is it?" Say the numbers in the list above. Say that nobody has used it except teammates.
- "What if it fails?" Default command is stop. Late, missing or unknown data gives stop. The ESP32 stops the wheels on its own if the laptop goes quiet. The operator has SPACE and a kill switch. Do not give a stop time unless you measured one.
- "Has it driven on the floor?" Answer with D3's result, plainly.

### When something fails live
Rule: when anything odd happens near the wheels, the operator hits the kill switch first, and everyone talks after.

| What fails | What the operator and presenter do |
| --- | --- |
| The chair moves when it should not, or does not stop | Operator: kill switch, then SPACE. Presenter: "That is why there is a kill switch." Log it in `PROGRESS.md` after. Do not run the chair again in front of judges. |
| The wheel does not turn | Pratosh checks the port name and that the battery is on. One retry. If it fails again, switch to screen-only and show the video clip of the wheel (shot 6B or 6A). Say the clip is a recording. |
| The serial port is missing or an error about the dongle appears | Port is wrong. Run `ls /dev/cu.*`, pick the ESP32 port, never the `usbserial-DM...` port. One retry. |
| Gaze will not hold on an object | Press C while the rider looks at the +. One retry. If no, Prakhar runs the route preview with the mouse and says so. |
| The phone camera freezes or the picture goes black | The chair stops by itself. Say so only if it happened. Restart the program. If it is still dead, switch to the video. |
| The jaw clench does not confirm twice in a row | Vani switches to dwell (`--confirm dwell`). Say "dwell works, the clench is the part we are still tuning". |
| Gemini is slow or offline | Route preview shows a dashed "unverified" route. Say what the screen says. Or run with `--scene-ai off`. Nothing else changes. |
| The laptop crashes | Kill switch not needed if nothing is moving. Restart. Show the video while it boots. |
| A judge asks something we have not measured | "We have not measured that" is a correct answer. |
| Battery dies | Show the screen-only part and the video. |

Backup that always works: the unlisted video from Devpost on the laptop, offline copy on the desktop, and the
screen-only part (`object_select` with nothing driving).

## If everything goes wrong at 1:30 am
The submission still has: the screen-only shots, the route preview, the left wheel on the bench, the hardware laid out.
That is a true, smaller demo. Submit it, say "bench" and "left wheel only", and do not claim Best Physical AI.
