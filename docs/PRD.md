# PRD: SSVEP BCI Wheelchair

> **Status (Sat Nov 14).** This document describes the original SSVEP plan. What exists today: the rider looks at an
> object or arrow on the laptop screen (webcam gaze), confirms by dwell or a jaw clench read through the OpenBCI
> headset, and the chair drives through the ESP32 bridge. Only the flicker screen of the SSVEP plan was built: there
> is no SSVEP decoder and no closed-eyes (alpha) detector. See `docs/PROJECT_CONTEXT.md` and `PROGRESS.md`.

## Problem
People with high spinal cord injury, ALS or severe cerebral palsy often cannot use a joystick. Existing
alternatives (sip-and-puff, head arrays, eye-gaze trackers, attendant control) are slow, need residual motor
control, or take independence away. Clinical BCI systems exist but are expensive and lab-bound.

## Who it is for
A wheelchair user with reliable gaze but little or no hand control, plus their caregiver.

## The product in one sentence
Look at a flickering arrow and the chair moves that way; look away or close your eyes and it stops.

## Mode 1: manual arrows (must-have)
The exact, observable acceptance criteria are in section 1.3 of `.cursor/plans/ssvep-chair.plan.md`: forward
after about 3 s of gaze, turns, stop within about 1 s on look-away or closed eyes, obstacle stop, kill switch,
never moving with nobody looking, and three passes in a row.

## Mode 2: autonomous (stretch, only after Mode 1 passes)
1. Camera feed shows up to 4 detected objects, each with a flickering box.
2. Wearer picks one by gaze; chair turns to center it, drives toward it, stops near it.
3. Any lost track, obstacle or eyes-closed -> STOP.

## Non-goals this weekend
Medical-grade accuracy, outdoor use, user accounts, cloud anything, a mobile app.

## Tracks (from the onsite packet)
- Main track (exactly one): Healthcare.
- Special: Best Hardware Hack. Best Physical AI Hack only if Mode 2 works (AI must be in the hardware build).
- Possible add-ons: Photon messaging agent (texts caregiver on E-STOP); not core.

## Judging criteria mapping (onsite packet)
| Criterion | Our answer |
| --- | --- |
| Creativity | Planned: brain signals instead of hands, eyes-closed stop. Today: gaze plus jaw clench; no closed-eyes stop exists |
| Utility | It drives, live, in front of the judge |
| Charity | Independence for people who cannot use a joystick |
| Avidity | Honest demo, clear what's next (more targets, calibration-free, clinical partners) |

## Open questions
See decisions D1-D8 and section 12 in `.cursor/plans/ssvep-chair.plan.md`.
