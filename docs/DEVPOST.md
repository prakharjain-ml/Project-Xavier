# Devpost draft: Project Xavier

> Status: DRAFT (Sat Nov 14, evening). Lines marked **[TODO]** need a real result before submission.
> Submit by **Sun 7:15 am**. Tracks: **Healthcare** (main) + **Best Hardware Hack** [+ Best Physical AI Hack only if
> the chair drives to a chosen object by the 1 am freeze].

## Name and tagline
**Project Xavier**
**Tagline:** Closing the loop between human intent and autonomous motion.
**Elevator pitch:** Hands-free mobility powered by biosignals, computer vision, and real-time path planning.
(Only if SSVEP brain-signal control works on the rider by the freeze: "An automated wheelchair controlled via EEG
signals and real-time path planning." Until then, the control is gaze + an EEG-headset jaw clench, so say that.)

## Why "Xavier"
Charles Xavier, the professor from X-Men, might be the most famous wheelchair user in fiction. He runs a school,
leads a team and gets around without ever touching a joystick. He has Cerebro, a helmet that amplifies his brain
waves, and in the 90s animated series he floats around in a hover chair.

We had a hoverboard, a hobby EEG headset and a weekend. The joke wrote itself, and then it stopped being a joke.
Our "Cerebro" is an OpenBCI board with gel electrodes. Our hover chair is a split hoverboard we re-flashed by hand.
And the idea is the same one the comics had decades ago: mobility should follow intent, not hands.

There is one honest difference. Xavier reads minds. We read signals: where the rider's eyes go, a deliberate
clench of the jaw picked up by the EEG headset, and, next, the visual cortex responding to flickering targets.
It is a smaller superpower, but it is a real one, and it runs on parts that cost a fraction of a clinical system.
(Project Xavier is a fan reference; we are not affiliated with Marvel.)

## Inspiration
People with ALS, high spinal cord injury or severe cerebral palsy often lose the hand control a joystick wheelchair
needs, but keep their eye movements and some facial muscles. The alternatives (sip-and-puff, head arrays,
commercial eye-gaze systems, or a caregiver pushing the chair) are slow, tiring, expensive or take away
independence. We wanted to see how far a team of four could get in 36 hours with parts that cost a fraction of
clinical systems, without cutting corners on safety.

## What it does
- **Look to steer.** The laptop in front of the rider shows four large arrows. A webcam tracks where the rider is
  looking; holding their gaze on an arrow for 1.5 s starts the chair moving that way. Looking away, at the centre,
  or closing their eyes stops it immediately (hold-to-move: the chair only moves while the rider keeps choosing).
- **Look at a real object to choose it.** A phone camera on the back of the laptop shows the room. YOLO finds
  chairs, tables and people and draws a box around each; the box under the rider's gaze turns yellow.
- **Clench to confirm.** A jaw clench, picked up by the OpenBCI headset as a muscle (EMG) signal, confirms the
  choice (the box turns green). A deliberate clench means stray glances never trigger anything.
  **[TODO: Vani's live jaw test numbers, e.g. "10/10 clenches confirmed, 0 false confirms while talking".]**
- **Smart suggestions.** Gemini looks at the camera view and ranks the places the rider most likely wants to go
  (doors, a table with their things, a person) so the few choices on screen are the useful ones.
- **Distance and pathfinding.** The chair estimates how far each object is (camera calibrated against a measured
  distance) and plans a path around obstacles with the Dynamic Window Approach.
  **[TODO: say "in simulation" unless drive-to-object runs on the real chair by the freeze.]**

## How we built it
**The chain** (each part talks to the next through a small written contract, so parts could be built in
parallel and swapped):
```
eyes  -> webcam + EyeTrax (own process)        -> gaze point on screen
jaw   -> OpenBCI Cyton + our EMG detector       -> "confirm"
room  -> phone camera + YOLO + ByteTrack (+Gemini) -> objects, distance -> DWA path planner
           -> safety state machine (STOP is the default, 20 Hz) -> laptop motor driver
           -> USB serial -> ESP32-S3 safety bridge -> UART -> hoverboard boards (open-source FOC firmware) -> wheels
```
- **Hardware:** a split hoverboard (two GD32E235 boards, one per wheel) re-flashed with the open-source
  RoboDurden firmware over SWD; an ESP32-S3 bridge that converts laptop commands into the boards' 9-byte frames;
  a plank chair with casters; a kill switch on the battery line; an ultrasonic sensor.
- **Safety, in layers:** (1) hardware kill switch; (2) ESP32 watchdog: if the laptop goes quiet for 200 ms the
  wheels stop, plus its own ultrasonic obstacle stop and speed cap; (3) a state machine where every unknown,
  stale or low-confidence input means STOP, tested rule by rule; (4) gaze and confirmation rules (1.5 s dwell,
  0.3 s look before a clench counts, blinks under 0.4 s ignored).
- **Software:** Python on one MacBook Air: pygame screen, OpenCV, Ultralytics YOLO + ByteTrack, MediaPipe/EyeTrax,
  BrainFlow, Gemini, NumPy/SciPy. **250+ automated tests**, plus "mutation checks" where we deliberately broke a
  safety rule to prove a test would catch it.

## Challenges we ran into
- **Finding the hoverboard's serial port.** The obvious pads and the 4-pin plug were not connected to the chip.
  After hours with a debugger and multimeter we found the link on the 5-pin plug, and that a missing solid
  ground was turning every byte into 60 Hz mains hum.
- **The EEG.** Our first recordings were saturated on every channel (a reference/ground problem) and the board was
  streaming at 1000 Hz, not the 250 Hz we assumed, which briefly fooled our own analysis into "seeing" a brain
  signal that was really mains hum. We caught it by checking the timestamps.
- **Webcam eye tracking.** Our first tracker read up/down badly and drifted when the rider moved; we measured
  why (vertical eye features are weak, calibration depends on head position), then adopted the more accurate
  open-source EyeTrax library and calibrate in the rider's seat every session.
- **Object tracking IDs churned** (296 IDs in 4 minutes), resetting the gaze dwell. The cause was our own code
  filtering detections before the tracker; fixing it brought it to 4 IDs in 30 s.
- **Pixel webcam mode drops out** when the phone sleeps; the app now detects which camera is which by whether
  it sees a face, and stops with a clear message if one is missing.

## Accomplishments that we're proud of
- **[TODO: the hoverboard driving from the laptop, wheels-up / on the floor, from Keshav and Pratosh's tests.]**
- Eyes alone drove all four arrows in a live test; looking away always stopped.
- A safety design we can explain to a judge in one breath: kill switch, independent watchdog, STOP by default.
- Re-flashing a hoverboard board with no documentation, from chip unlock to working motor control.

## What we learned
- Measure before believing: sample rates, field of view, wheel directions; nearly every big bug was an assumption.
- Webcams track left/right far better than up/down: design the interface around the sensor's strengths.
- A muscle signal (jaw clench) through an EEG headset is far more reliable for "yes" than decoding thoughts.

## What's next
- Brain-signal (SSVEP) confirmation once electrode contact is reliable (the flicker screen is built and timed).
- Three ultrasonic sensors and wheel odometry for real obstacle avoidance on the floor.
- Testing with the people this is for, and with clinicians, before any claim of medical use.

## Built with
Python, OpenCV, pygame, Ultralytics YOLO, ByteTrack, MediaPipe, EyeTrax, BrainFlow, OpenBCI Cyton, Google Gemini,
NumPy, SciPy, ESP32-S3 (Arduino), GD32E235, RoboDurden hoverboard firmware, OpenOCD, PythonRobotics (DWA)

## Honest limitations (say these out loud in judging)
- Not a medical device; tested only by our team. Gaze tracking needs good light and recalibration if the
  laptop moves. The jaw clench is a muscle signal, not mind reading. **[TODO: floor driving permitted / on a stand.]**

## Media checklist (film as we go)
- [ ] Hoverboard wheels following laptop commands (forward / back / turn / watchdog stop)
- [ ] Rider steering the arrows with her eyes; looking away -> stop
- [ ] Jaw-clench test with CONFIRM lines on screen
- [ ] Looking at a chair in the camera view -> yellow -> clench -> green
- [ ] Kill switch press, ultrasonic stop with a hand in front
- [ ] 2-minute video: problem (10 s) -> demo (80 s) -> safety (20 s) -> what's next (10 s)
