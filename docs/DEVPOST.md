# Devpost: Xavier (paste-ready once every [VERIFY] is filled or deleted)

Main track: **Healthcare** (exactly one). Special tracks: **Best Hardware Hack** [+ Best Physical AI Hack only if
the chair drives itself to a chosen object in the live demo]. Submit by 7:45 am. Discord usernames: [VERIFY: all four].

---

**Project name:** Xavier

**Elevator pitch (under 200 characters):** A hoverboard wheelchair you steer with your eyes and confirm with a jaw
clench, read by an OpenBCI headset. Every unclear signal means stop.

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
3. It moves only while they keep looking. Looking at the centre or away stops it within 50 ms.
4. In object mode, the phone on the back of the laptop boxes chairs and people. The box under the gaze turns
   yellow; a jaw clench, read by an OpenBCI electrode behind the ear, turns it green. [VERIFY: keep only if it
   works on Vani at the table.]

[VERIFY: say whether the wheels carry a rider, run on a stand, or are bench-tested unloaded.]

## How we built it
EyeTrax, an open-source gaze library, sends a gaze point for every webcam frame. YOLO and ByteTrack box objects in
the phone feed. BrainFlow streams the Cyton to the laptop, and our detector measures 40 to 200 Hz muscle energy
every 0.1 s, skipping mains hum. A clench counts only after 0.3 s, and calibration refuses to start unless a clench
is at least three times stronger than rest.

A state machine running 20 times a second turns those signals into wheel speeds, and its default answer is stop.
An ESP32-S3 converts the speeds into 9-byte frames for the hoverboard's two boards, which run the open-source
RoboDurden firmware we flashed. If the laptop goes quiet for 200 ms, the ESP32 stops the wheels on its own.

One decision shaped the build: gaze alone selects whatever you glance at (the Midas-touch problem). So gaze picks,
and a deliberate clench confirms.

## Challenges we ran into
The hoverboard was dead for [VERIFY: hours] hours. Its TX/RX pads and 4-pin plug weren't connected to the chip;
the serial link was the 5-pin plug. Even then every byte was garbled, because our ground wasn't a real ground and
the ESP32 was reading mains hum. A wire to the battery's negative fixed it, and the left wheel answered our laptop.

Our first 15 Hz recording looked like brain data. There was no peak at 15 Hz. The same peaks at 9.75, 19.5 and
29.25 Hz sat on every channel, unplugged ones included, and two channels were identical. We rewired the electrodes
and now check the signal before every session. [VERIFY: what fixed it.]

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
- Steer with brain signals alone. The flicker screen is built; EEG decoding still has to pass on a real head.
- Drive to the chosen object. The path planner avoids obstacles in simulation; next it runs on the chair.
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
| Clench confirm on Vani (step 4, accomplishment 3, caption 2) | `python -m bci.jaw_live ... --channels 1` output: ratio line + CONFIRM count |
| Hoverboard hours dead, time it worked, right wheel | Keshav / Pratosh |
| What fixed the 9.75 Hz signal | the person who rewired it |
| One lesson per teammate | each teammate |
| Gemini in Built with | only if the demo runs `--gemini` |
