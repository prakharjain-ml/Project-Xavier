# 2-minute demo script (draft, fill in Sunday)

What the demo is: the rider looks at an object on the laptop screen (webcam gaze), confirms by holding the gaze
1.5 s (dwell) or by a jaw clench read through the OpenBCI headset, and the chair drives toward it while the rider
keeps looking at it. The original plan (flickering arrows, SSVEP brain signals, closed-eyes stop) is not part of
this demo: no SSVEP decoder and no closed-eyes detector exist. Status of each piece: `PROGRESS.md`, and the audit in
`docs/PROJECT_CONTEXT.md` section 8.

Label used below: **UNPROVEN** = not yet shown on real hardware. Run it wheels-up first and write the result in
`PROGRESS.md` before it goes in the demo.

## Programs and flags that exist (HUMANS run the serial ones)
| Step | Command | Touches |
| --- | --- | --- |
| Objects + dwell, nothing drives | `python -m vision.object_select` | both cameras |
| Same, jaw clench confirms (practice board) | `python -m vision.object_select --confirm jaw --jaw-board synthetic` (J injects a fake clench) | both cameras |
| Same, real headset | `python -m vision.object_select --confirm jaw --jaw-port /dev/cu.usbserial-...` | cameras + headset |
| Drive into a fake port | `python -m vision.object_select --drive --mock` | both cameras |
| Drive the real chair | `python -m vision.object_select --drive --serial PORT [--confirm dwell\|key\|jaw]` | motors |
| Arrows by gaze (fallback) | `python app.py --gaze --mock` or `--serial PORT`; `--keyboard` uses the arrow keys | eye camera, motors with `--serial` |
| Route preview, drives nothing | `python -m vision.nav_preview` (`--scene-ai off` keeps frames on the laptop; the default sends frames to Gemini) | forward camera |

Keys in `object_select`: C re-centres the gaze, X cancels the confirmation, J confirms in key mode, Q or ESC quits.

## Before anyone sits on it
1. A teammate is the rider. Never a judge or a stranger.
2. A second teammate is the operator, walking beside the chair, with a hand on the battery kill switch. The kill
   switch is the stop to trust. [UNPROVEN: no record that it is fitted; confirm.] What the operator key does in the
   object program: see `PROGRESS.md`.
3. Wheels up first, then the floor with at least 3 m clear, minimum speed. Any uncommanded motion: stop, log it in
   `PROGRESS.md`, and repeat wheels-up.
4. Before any `--serial` run, check the bridge answers (distance lines arrive) and wave a hand in front of the
   ultrasonic sensor. [UNPROVEN: no test result for the sensor in the repo.]

## Script
| Time | Who | What |
| --- | --- | --- |
| 0:00-0:15 | Prakhar | Problem in one sentence: people who can't use a joystick lose independence. |
| 0:15-0:30 | Prakhar | How: the rider looks at an object, confirms with a clench or a held gaze, and the chair drives to it. |
| 0:30-1:25 | Rider + Prakhar | Live: gaze picks a box (yellow), confirm (green) [jaw clench: UNPROVEN on a real head; dwell is the fallback], chair drives toward it [UNPROVEN with the real camera and wheels], look away and it stops [stop time not measured], operator hits the kill switch. |
| 1:25-1:40 | Prakhar | Safety recap: stop is the default command, the ESP32 watchdog, an ultrasonic cutoff [UNPROVEN], the battery kill switch. |
| 1:40-2:00 | Prakhar | What we learned and what's next: brain-signal steering (flicker screen built, no decoder), more objects, testing with real users. |

If the chair or the clench is not working by showtime, show only what works: gaze picks an object on screen
(`object_select` with nothing driving) and say plainly what has not been run on the chair.

## Judge interruptions to rehearse
- "What happens if the signal drops?" -> no gaze, closed eyes or a lost face means no motion command. Camera-freeze
  and operator-key behaviour: see `PROGRESS.md`. Say only what you have shown.
- "How accurate is it?" -> only numbers in `PROGRESS.md`: gaze on arrows, 11 of 23 selections on a fake port; gaze on
  objects, 3 confirmations and 0 false (`docs/GAMEPLAN_SAT.md`). No jaw numbers from a real head exist yet.
- "Why not just eye tracking?" -> gaze alone selects whatever you glance at, so a second deliberate signal (a clench)
  confirms. Honest answer: dwell alone works too, and we have not shown the clench on a real head.
- "Where is the brain-signal part?" -> the first plan was SSVEP; our first recording had no usable signal, so we
  switched to gaze plus jaw clench. The jaw clench is a muscle signal, not a brain signal.
- "What did you personally build?" -> each person names their folder.
