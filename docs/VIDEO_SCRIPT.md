# VIDEO_SCRIPT: Xavier demo video (about 2:00)

Written Sat Nov 14, about 7 pm. Owner: Prakhar. Editor: Prakhar. Plan for filming and sleep: `docs/RUN_OF_SHOW.md`.

## Rules for this video
1. Length: 2:00 or less. The team's playbook (`docs/TEAMMATE_GUIDE.md` section 5, item 2) says: at most 2:00, filmed from
   two angles, close-up of the screen, a stop shown, the kill switch shown, and an object-approach clip only if it
   worked. Note: `docs/DEVPOST.md` has no video section, so that is the source. The playbook was written for the
   SSVEP plan. Its flicker arrows, eyes-closed stop and look-away timing are not in this video, because we have no
   SSVEP decoder, no eyes-closed detector, and no stop time measured.
2. The video must not show or imply the chair doing something it has not done. Every clip carries a caption that
   says what it is: "WHEELS OFF THE GROUND", "LEFT WHEEL ONLY", "SCREEN ONLY", "MOUSE STANDS IN FOR THE EYES".
3. Every shot has a fallback that can be filmed tonight with things that already work. The final cut uses the
   primary shot only if the "must be true" line was true when it was filmed. Otherwise use the fallback.
4. Say "jaw clench" and "muscle signal". Never say "brain-controlled". The clench is read by the OpenBCI headset as
   muscle, not as a brain signal.
5. Say "prototype" in shot 1 or 2. No numbers in the voice-over except ones in `PROGRESS.md`
   or measured tonight and written in `PROGRESS.md`. Numbers we may use today: 1.5 s dwell, the 200 ms watchdog setting
   (a setting, not a measured stop time), 11 of 23 arrow selections on a test port, 0.3 s clench hold.
6. A person never sits on the chair in this video unless the team decided it in the 12:00 am decision
   (`docs/RUN_OF_SHOW.md`) and the run was done.
7. Video files are never committed (`.mov`, `.mp4`). Save them in `~/Movies/xavier-video/`.

## Status of each thing the video could show (Sat 7 pm)
| Thing | Status | Source |
| --- | --- | --- |
| Left wheel turns under laptop control, stops when the laptop goes quiet | Proven on hardware | `PROGRESS.md` (Keshav's handoff) |
| Right wheel | Not finished | `PROGRESS.md` |
| Gaze picks arrows | Proven live with a mock motor port: 11 of 23 selections held to moving | `PROGRESS.md` |
| Gaze dwell confirms an object | Proven live, nothing driving | `docs/GAMEPLAN_SAT.md` (3 confirmations, 0 false) |
| Route preview (outlines, cursor, route, stop ring) | Works on screen. Software to follow it exists (`--follow route`) but has never run on the chair | `docs/ROUTE_REQUIREMENTS.md` |
| Jaw clench from a real head | Never seen. Synthetic data only | `docs/PROJECT_CONTEXT.md` section 8 |
| Chair drives to an object a rider looked at | Never seen, not even wheels up | `docs/PROJECT_CONTEXT.md` section 8 |
| SPACE stop, frozen-camera stop, soft start, arrival | Landed tonight in software; untested on hardware | `PROGRESS.md` |
| Ultrasonic stop, kill switch, watchdog on the real chair | No record they were tested | `docs/SAFETY.md` status note |

## Shots (total 2:00)
Each shot: time, on screen, words, what must be true, fallback. "VO" = voice-over by Prakhar unless noted.
About 2.5 spoken words per second, so a 15 s shot holds about 35 words at most.

### Shot 1. 0:00-0:12. The problem
- On screen: the hardware laid out on a table, slow pan. No person in a wheelchair. Caption: "Xavier. A prototype built in 36 hours."
- Words (VO): "A power wheelchair needs a hand on a joystick. Some people lose that hand and keep their eyes and their jaw. We built a prototype that tries to use those."
- Must be true: the items on the table are the real ones (laptop, phone camera, OpenBCI board and headset, ESP32, hoverboard base).
- Fallback: none needed. This shot depends on nothing unproven.

### Shot 2. 0:12-0:27. The parts
- On screen: close shots of each part in turn, with a lower-third label: "Laptop webcam: where the rider looks", "Phone camera: sees the room", "OpenBCI headset: jaw muscle", "ESP32 safety bridge", "Hoverboard base".
- Words (VO): "The laptop webcam finds where the rider looks. A phone camera sees the room. The headset reads a jaw clench. An ESP32 checks every command and stops the wheels if the laptop goes quiet. The hoverboard motors do the driving."
- Must be true: the ESP32 watchdog is in `firmware/bridge/bridge.ino` at 200 ms. We say "stops if the laptop goes quiet", not a stop time. Do not say "ultrasonic stop" unless it was tested tonight.
- Fallback: none needed. If the headset is not on a head, label it "OpenBCI board", not "headset reading".

### Shot 3. 0:27-0:47. Gaze picks an object (screen only)
- On screen: split picture. Left: screen recording of `object_select` (outlines, eye cursor, reticle filling). Right: the rider's face, filmed by a second camera. Caption: "SCREEN ONLY. NOTHING IS DRIVING."
- Words (VO): "The rider looks at an object. The outline under the eyes gets a ring. If the rider keeps looking for 1.5 seconds, it is chosen. Here, nothing drives."
- Must be true: shot recorded with `python -m vision.object_select` (no `--drive`) and a real calibrated rider, no mouse. The pick shown happened in this take.
- Fallback: if gaze will not hold in any take, record the same screen with the mouse standing in for the eyes using `python -m vision.nav_preview`, and change the caption to "MOUSE STANDS IN FOR THE EYES". Do not cut a mouse take in as if it were gaze.

### Shot 4. 0:47-1:02. Confirm
- Primary (A), only if the jaw test passed tonight: close-up of the rider's face and the `object_select --confirm jaw` screen: the ring is full, a clench, the outline turns green. Caption: "JAW CLENCH, READ BY THE HEADSET. MUSCLE SIGNAL."
  - Words (VO): "To avoid choosing whatever the eyes glance at, a second signal confirms: a jaw clench, read as muscle by the headset. On Vani, [VERIFY: X of Y clenches confirmed, Z false while talking. Vani measures with `jaw_live`]."
  - Must be true: the real-head test in `docs/RUN_OF_SHOW.md` passed (10 clenches gave 9 or 10 confirms, talking gave 0), and this take shows a real clench from a real head, not the `J` key and not `--jaw-board synthetic`.
- Fallback (B): close-up of the dwell ring filling and turning green. Caption: "CONFIRM BY HOLDING THE GAZE 1.5 s. JAW CLENCH NOT YET WORKING ON A HEAD."
  - Words (VO): "Today the confirm is a held gaze of 1.5 seconds. The jaw clench is written and passes on practice data, but we have not read a clean clench from a real head yet."
- Fallback (C), if (A) was filmed but only half worked: use B in the cut and put the A footage nowhere.

### Shot 5. 1:02-1:17. The route preview
- On screen: screen recording of `nav_preview`: cyan outlines, cursor, the route drawn on the floor to a stop ring. Caption: "ROUTE PREVIEW. MOUSE STANDS IN FOR THE EYES. ROUTE FOLLOWING NOT YET RUN ON THE CHAIR."
- Words (VO): "This is the route we plan to the chosen object, drawn on the real floor. A second model can add no-go zones. It is a preview. The chair does not drive along it yet."
- Must be true: recorded live with `nav_preview` tonight. If `--scene-ai gemini` was on and the screen showed the solid "Gemini-checked" route, say "A second model adds no-go zones". If it showed the dashed "unverified" route, leave that sentence out. Update this caption if the team tests route-following on the chair before filming (then the last sentence changes, and only then).
- Fallback: show `docs/img/route_preview_design.jpg` as a still. Caption: "STILL FRAME FROM A TEST IN OUR HALL." Same words, but say "this still".

### Shot 6. 1:17-1:40. The wheels move
- Primary (A), only if the first wheels-up drive-to-object run worked: wide shot and a second angle. Chair on a stand, wheels off the ground, laptop screen visible, the rider (Vani) looks, confirms, and the wheels turn. Caption: "WHEELS OFF THE GROUND. NOBODY ON THE CHAIR."
  - Words (VO): "With the wheels off the ground, the rider looks at an object, confirms, and the wheels turn toward it. We have not driven this on the floor." (Edit the last sentence if a floor run happened: "On the floor, [VERIFY: how many runs, how many ended near the object]". Only if Prakhar logged those runs in `PROGRESS.md`.)
  - Must be true: the run used `object_select --drive --serial PORT` with real gaze, in this take. Both wheels turning must be true, or the caption says "LEFT WHEEL ONLY".
- Fallback (B), the bench: the laptop drives the left wheel, wheel visible, laptop screen visible. Run `python app.py --keyboard --serial PORT`: hold Up, the dwell bar fills over 1.5 s, the wheel turns; let go, it stops. Caption: "LEFT WHEEL ONLY. THE KEYBOARD STANDS IN FOR THE RIDER."
  - Words (VO): "Today, one wheel is finished. Here the laptop drives it: hold, wait 1.5 seconds, turn. Let go and it stops. The second wheel is not done."
  - Must be true: it is the left wheel, wheels off the ground or the board on the bench, and the soft start is visible: the wheel ramps up and does not jump. If the right wheel also works at that time, say "both wheels".
- Fallback (C), if the bench cannot be run: shot of the left wheel on the bench from the earlier session, only if someone filmed it. Otherwise cut this shot and spend the time on shot 7.

### Shot 7. 1:40-1:52. Stops
- On screen: operator presses SPACE: the E-STOP banner on the screen and the wheel stops. Then the operator's hand turns the kill switch and the wheel dies. Caption: "OPERATOR SPACE STOP. THEN THE BATTERY KILL SWITCH."
- Words (VO): "The default command is stop. Anything unknown, late or missing gives stop. A person with a hand on the kill switch can cut power at any time."
- Must be true: both stops were done on camera, with the wheel turning when they were pressed, wheels off the ground. SPACE stop and the kill switch are not recorded as tested anywhere else in the repo, so this shot is evidence for both. Do not say a stop time.
- Do not include: look-away stop, ultrasonic stop, "pull the USB" stop, unless each was filmed tonight and logged in `PROGRESS.md`.
- Fallback: if the kill switch is not fitted tonight, drop the second half of the shot and the last sentence of the VO, and do not show or mention a kill switch.

### Shot 8. 1:52-2:00. What is not done
- On screen: black card, white text, read by the VO: "Not done: right wheel. Chair drives to an object. Jaw clench on a real head." Only list the ones still true at filming time. Then team names and the repo.
- Words (VO): "This is a prototype. What is not done: [list from the card]. Next: test with people who use power wheelchairs."
- Must be true: the list matches `PROGRESS.md` at the time of the final cut. Prakhar re-reads it before export.
- Fallback: none needed.

## Silent-version rule
The video must make sense with the sound off: every shot has its caption. Judges may watch muted.

## Screen-recording commands
All run on the demo MacBook from the repo with the venv:
`cd "/Users/prakharjain/HP Auto WheelChair" && source ~/venvs/hp26/bin/activate`

Record the screen with the macOS tool `screencapture` (the first time, allow Terminal under System Settings, Privacy
and Security, Screen Recording). `-v` records video and `-V N` stops after N seconds. Use two terminal windows: start the
recorder in window 2, then run the program in window 1. Save files outside the repo.
`mkdir -p ~/Movies/xavier-video`

| Shot | Window 2 (recorder) | Window 1 (program) | Notes |
| --- | --- | --- | --- |
| 3, gaze picks, nothing drives | `screencapture -v -V 90 ~/Movies/xavier-video/s3_gaze.mov` | `python -m vision.object_select --seconds 80` | The program calibrates first (nine dots). Start the recorder after calibration if you want to skip it: the program stays open. Keys: C re-centre, X cancel, Q quit. |
| 4A, jaw confirms (only after the jaw test passed) | `screencapture -v -V 90 ~/Movies/xavier-video/s4_jaw.mov` | `python -m vision.object_select --confirm jaw --jaw-port /dev/cu.usbserial-XXXX --jaw-channels 1 --seconds 80` | Replace the port with the real dongle port (`ls /dev/cu.usbserial-*`). Vani runs this, not an agent. |
| 4B, dwell confirm close-up | `screencapture -v -V 60 ~/Movies/xavier-video/s4_dwell.mov` | `python -m vision.object_select --confirm dwell --skip-calibration --seconds 50` | `--skip-calibration` only if the rider has not moved since the last calibration. |
| 5, route preview, live | `screencapture -v -V 50 ~/Movies/xavier-video/s5_route.mov` | `python -m vision.nav_preview --scene-ai gemini --cam-height H --cam-pitch P --seconds 40` | Mouse is the cursor: rest it on an object for 1.5 s. S, SPACE, Q or ESC stop it. Gemini sends frames to Google and needs the key in `.env`. Without Wi-Fi use `--scene-ai off`, and expect a dashed "unverified" route. H and P: [VERIFY: Pratosh or Vani measures the phone's height in metres and tilt in degrees on the chair; the defaults are 0.89 m and level]. |
| 5, route preview, a still | none | `python -m vision.nav_preview --image PHOTO --cursor 0.87,0.60 --no-window --save ~/Movies/xavier-video/s5_still.png` | PHOTO is a still of the hall. This path draws no window. |
| 6B, bench, keyboard drives the left wheel | Film the wheel and screen with a phone, no screen recording | `python app.py --keyboard --serial PORT` | HUMANS ONLY: Pratosh or Keshav. Wheels off the ground, kill switch in a hand. Hold Up, release, SPACE, R re-arms. |
| 6A, wheels-up drive to an object | Film with two phones | `python -m vision.object_select --drive --serial PORT --confirm dwell` | HUMANS ONLY. After the wheels-up safety pass in `docs/RUN_OF_SHOW.md`. SPACE latches a stop, R re-arms. |

Screen-recording does not capture the room, so the shots with wheels, the rider and the hardware are phone video, not
`screencapture`. Check that the recorder and the program do not compete for the cameras: `screencapture` records the
display only and does not open any camera, so it is safe next to the program.

Trim and join without re-doing the edit: `ffmpeg -i in.mov -ss 00:00:05 -t 00:00:20 -c copy out.mov` (ffmpeg was verified
on Prakhar's laptop, `PROGRESS.md` gate log). Export one file at 1080p, 2:00 or less, upload to YouTube as unlisted.

## Shot list (what to capture, who films, who is on camera, minutes)
Times are hands-on minutes. Camera operators use phones unless noted.

| # | What to capture | Who films | Who is on camera | Minutes |
| --- | --- | --- | --- | --- |
| 1 | Hardware on a table, slow pan, steady | Prakhar | nobody | 5 |
| 2 | One close-up per part (laptop, phone mount, headset on a stand or on Vani, ESP32, hoverboard) | Prakhar | Vani holds the headset | 10 |
| 3 | Screen recording of gaze picks, plus the rider's face on a second phone | Prakhar runs the recording; Pratosh films the face | Vani (rider) | 15 |
| 4A | Jaw confirm, screen recording plus face close-up, 3 clean takes | Vani runs it; Pratosh films | Vani | 10, only if the jaw test passed |
| 4B | Dwell ring close-up | Prakhar | Vani | 5 |
| 5 | Route preview recording, two takes, one with `--scene-ai off` | Prakhar | nobody | 10 |
| 5 still | Render the still from a hall photo | Prakhar | nobody | 2 |
| 6B | Bench: left wheel driven by `app.py --keyboard`, two angles, three takes | Keshav films; Pratosh drives | Pratosh's hands | 15 |
| 6A | Wheels-up drive-to-object, two angles, up to 3 takes | Keshav and Vani film | Vani (rider) | 20, only if it works |
| 7 | SPACE stop and kill switch, wheel turning when pressed, two angles | Vani films | Pratosh presses SPACE; Keshav turns the kill switch | 10 |
| 8 | Group shot at the table (the card and the repo go on in the edit) | Anyone, on a tripod or a stack of books | all four | 3 |
| V | Voice-over, read twice, in a quiet room, phone voice memo | Prakhar | n/a | 15 |

Minimum set if tonight falls apart: shots 1, 2, 3, 4B, 5, 6B (or a cut of it), 7 (SPACE only), 8, V. About 80 minutes.
That set uses only things that have worked.

## Order of work
1. Tonight, before anything with wheels: shots 1, 2, 3, 4B, 5, 5 still (Prakhar, alone with a rider for 3 and 4B). These are screen-only.
2. After the wheels-up safety pass: 7 and 6B (the safety pass is also the take).
3. Only if each gate in `docs/RUN_OF_SHOW.md` passes: 4A and 6A.
4. Voice-over last, after the cut is known, so the words match the footage that exists.
5. Cut a "safe version" (fallbacks only) first, upload it unlisted as insurance, then swap in any primary shots that earned it.
