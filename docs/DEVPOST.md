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
away and leave the eyes and the jaw. The alternatives we read about, like sip-and-puff straws and head arrays,
still make the person steer every turn, one small command at a time.

We named it after Charles Xavier, the X-Men professor who gets around by intent instead of hands. He has Cerebro.
We have an OpenBCI board and a hoverboard we re-flashed ourselves.

## What it does
Xavier lets someone choose where to go with their eyes and confirm it with their jaw.

1. A webcam on the laptop tracks the rider's gaze. Four arrows fill the screen.
2. The rider holds their gaze on an arrow. After 1.5 seconds the chair starts moving that way.
3. It keeps moving only while they keep looking. Looking at the centre or away stops it on the next 50 ms tick.
4. In object mode, the phone camera on the back of the laptop boxes chairs, tables and people. The box under the
   rider's gaze turns yellow, and a jaw clench, read by an OpenBCI electrode behind the ear, turns it green.
   [VERIFY: keep step 4 only if the clench confirm works on Vani at the table.]

[VERIFY: say plainly whether the wheels in the demo carry a rider, run on a stand, or are bench-tested unloaded.]

## How we built it
Follow one choice from the eye to the wheel. EyeTrax, an open-source webcam gaze library, runs as its own process
and sends a gaze point for every camera frame. YOLO and ByteTrack box objects in the phone feed. The OpenBCI Cyton
streams to the laptop through BrainFlow, and our detector measures 40 to 200 Hz muscle energy every 0.1 s,
skipping the bands around 60 Hz mains hum. A clench counts only if it holds for 0.3 s, and calibration refuses to
start if a clench isn't at least three times stronger than rest.

The gaze and the clench feed a state machine that runs 20 times a second, and its default answer is stop. It sends
wheel speeds to an ESP32-S3 every 50 ms. The ESP32 turns them into 9-byte frames for the hoverboard's two boards,
which we flashed with the open-source RoboDurden firmware. If the laptop goes quiet for 200 ms, the ESP32 stops the
wheels on its own.

The decision that shaped the build: gaze alone selects whatever you happen to look at (the Midas-touch problem).
So gaze picks, and a separate, deliberate signal confirms.

## Challenges we ran into
The hoverboard was dead for the first [VERIFY: hours] hours. The board's round TX/RX pads and its 4-pin plug turned
out not to connect to the chip. The serial link was the 5-pin plug, and even then every byte came out garbled
because our ground wire wasn't a real ground. The ESP32 was reading mains hum. A wire to the battery's negative
fixed it, and the left wheel finally answered our laptop. [VERIFY: the time, and the right wheel.]

Our first 15 Hz recording looked like brain data. It wasn't. There was no peak at 15 Hz, and the same peaks at
9.75, 19.5 and 29.25 Hz showed up on every channel, including unplugged ones. Two channels were identical. We
rewired the electrodes and now check the signal before every session. [VERIFY: what fixed it on the board.]

## Accomplishments that we're proud of
- Commands from our laptop drove the hoverboard's left wheel forward, backward and in a turn, and stopped it when
  the laptop went silent. [VERIFY: both wheels; loaded or bench.]
- With eyes only, a teammate reached all four directions: 11 of 23 gaze selections held long enough to move (motor
  commands on a test port).
- [VERIFY: "The clench read [N]x stronger than rest on Vani, and confirmed [X] of [Y] clenches with [Z] false
  triggers while talking."]

## What we learned
- A spectrum full of peaks can look like success. Comparing against unplugged channels showed us it was noise.
- A missing ground wire cost us more hours than any algorithm.
- [VERIFY: one lesson from each teammate, in their own words.]

## What's next
- Steer with brain signals alone. Our flicker screen is built and frame-timed; the EEG decoding still has to pass on
  a real head.
- Drive to the chosen object. The path planner avoids obstacles in simulation; next it runs on the chair.
- Test with people who use power wheelchairs. Everything we know comes from our own heads.

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
