# Devpost: Xavier (paste-ready once every [VERIFY] is filled or deleted)

Main track: **Healthcare** (exactly one). Special tracks: **Best Hardware Hack** [+ Best Physical AI Hack only if
the chair drives itself to a chosen object in the live demo]. Submit by 7:45 am. Discord usernames: [VERIFY: all four].

---

**Project name:** Xavier

**Elevator pitch (under 200 characters):** A hoverboard wheelchair you steer with your eyes and confirm with a jaw
clench, read by an OpenBCI headset. Its default command is stop. [VERIFY: jaw clench read from a real head]

**Gallery tagline:** Closing the loop between human intent and autonomous motion.

## Inspiration
A power wheelchair assumes a hand that can push a joystick. A high spinal cord injury or ALS can take that hand
and leave the eyes and the jaw. Sip-and-puff straws and head arrays still make the person steer every turn.

We named it after Charles Xavier, the X-Men professor who gets around by intent, not hands. He had Cerebro. We
have an OpenBCI board and a hoverboard we re-flashed ourselves.

## What it does
Xavier lets someone choose a direction with their eyes and confirm it with their jaw.

1. A webcam tracks the rider's gaze across four arrows on the laptop.
2. Holding the gaze on an arrow for 1.5 s starts the chair that way.
3. It moves only while they keep looking. Looking at the centre or away stops it. [VERIFY: stop time, measured
   from the gaze leaving to the wheels stopping. No end-to-end timing exists yet.]
4. In object mode, the phone on the back of the laptop boxes chairs and people. The box under the gaze turns
   yellow; a jaw clench, read by an OpenBCI electrode behind the ear, turns it green. The chair then drives
   toward that object while the rider keeps looking at it. [VERIFY: keep only if the clench works on Vani at
   the table, and only if the drive-to-object run has been done on the real chair.]

[VERIFY: say whether the wheels carry a rider, run on a stand, or are bench-tested unloaded.]

## How we built it
EyeTrax, an open-source gaze library, sends a gaze point for every webcam frame. YOLO and ByteTrack box objects in
the phone feed. BrainFlow streams the Cyton to the laptop, and our detector measures 40 to 200 Hz muscle energy
every 0.1 s, skipping mains hum. A clench counts only after 0.3 s above a threshold set from the rider's own rest
and clench levels.

A safety state machine turns those signals into wheel speeds, and its default answer is stop. It runs at 20 Hz in
the arrows app. [VERIFY: rate in object mode, where it runs once per video frame.]
An ESP32-S3 converts the speeds into 9-byte frames for the hoverboard's two boards, which run the open-source
RoboDurden firmware we flashed. If the laptop goes quiet, the ESP32's watchdog zeroes the wheels on its own. It is
set to 200 ms. [VERIFY: measure the stop time on the chair, with the laptop hung and with the USB cable pulled.]

One decision shaped the build: gaze alone selects whatever you glance at (the Midas-touch problem). So gaze picks,
and a deliberate clench confirms.

## Challenges we ran into
The hoverboard was dead for [VERIFY: hours] hours. Its TX/RX pads and 4-pin plug weren't connected to the chip;
the serial link was the 5-pin plug. Even then every byte was garbled, because our ground wasn't a real ground and
the ESP32 was reading mains hum. A wire to the battery's negative fixed it, and the left wheel answered our laptop.

Our first 15 Hz recording looked like brain data. There was no peak at 15 Hz. The same peaks at 9.75, 19.5 and
29.25 Hz sat on every channel, unplugged ones included, and two channels were identical. As of Saturday evening
the headset had not given us a usable recording, and we have no SSVEP decoder. We switched the plan to gaze plus
a jaw clench. [VERIFY: current state of the headset signal, and what fixed it if it is fixed.]

## Accomplishments that we're proud of
- Our laptop drove the hoverboard's left wheel forward, backward and in a turn, and the wheel stopped when the
  laptop went silent. [VERIFY: both wheels; loaded or bench.]
- Eyes only, a teammate reached all four directions: 11 of 23 gaze selections held long enough to move (test port).
- [VERIFY: "On Vani, a clench read [N]x stronger than rest; [X] of [Y] clenches confirmed, [Z] false triggers while
  talking."]

## What we learned
- A spectrum full of peaks can look like success. Unplugged channels showed us it was noise.
- One missing ground wire cost us more hours than any algorithm.
- [VERIFY: one lesson per teammate, in their words.]

## What's next
- Steer with brain signals alone. The flicker screen is built; the EEG decoder is not written, and nothing has
  passed on a real head yet.
- Drive to the chosen object reliably. The planner has only run in simulation and on a fake serial port; next it
  runs on the chair with a real camera.
- Test with people who use power wheelchairs. So far we've only tested on ourselves.

**Built with:** python, opencv, ultralytics-yolo, bytetrack, eyetrax, mediapipe, openbci-cyton, brainflow, numpy,
scipy, pygame, esp32-s3, arduino, gd32, robodurden-firmware, openocd [VERIFY: add gemini only if the demo uses it]

---

## Media order and captions (outside the paste-ready copy)
1. **Action shot:** Vani in the headset, laptop showing a green box or a moving arrow, wheels in frame.
   Caption: "Gaze picks, a jaw clench confirms, the wheels move. [VERIFY: bench / loaded]."
2. **The clench signal:** the `jaw_live` screen with CONFIRM lines, or channel 1 in the OpenBCI GUI at rest and
   during a clench. Caption: "A clench reads [N]x stronger than rest, so talking doesn't trigger it."
3. **The diagram or the board close-up:** gaze + headset, then laptop, then ESP32, then hoverboard; or the 5-pin
   plug wiring. Caption: "The serial link was the 5-pin plug, not the pads labelled TX/RX."
Then the team at the table.

## Open verification markers
| Marker | Evidence needed |
| --- | --- |
| Discord usernames | from each teammate |
| Rider / stand / bench | how the wheels run in the live demo |
| Stop time after the gaze leaves (step 3) | timed from gaze leaving to wheels stopping, on the chair |
| Watchdog stop time | laptop hung and USB cable pulled, measured at the wheels; the code reads about 0.25 s and about 0.5 s |
| Drive to object (step 4) | a run with the real camera and the wheels, wheels-up first; see PROGRESS.md |
| State machine rate in object mode | log the loop rate during an `object_select --drive` run |
| Headset signal state / what fixed it | Vani, with a fresh recording |
| Clench confirm on Vani (step 4, accomplishment 3, caption 2) | `python -m bci.jaw_live ... --channels 1` output: ratio line + CONFIRM count |
| Hoverboard hours dead, time it worked, right wheel | Keshav / Pratosh |
| One lesson per teammate | each teammate |
| Gemini in Built with | only if the demo runs `--gemini` |
