# Devpost: Project Xavier

> DRAFT, Sat Nov 14 evening. **[TODO]** = needs a real result before we submit (deadline Sun 7:15 am).
> Tracks: **Healthcare** (main), **Best Hardware Hack**. Add **Best Physical AI Hack** only if the chair drives to
> a chosen object on its own by the 1 am freeze.

**Tagline:** Closing the loop between human intent and autonomous motion.
**Elevator pitch:** Hands-free mobility powered by biosignals, computer vision, and real-time path planning.

## Why "Xavier"
Charles Xavier, the professor from X-Men, might be the most famous wheelchair user in fiction. He runs a school,
leads a team and gets around without ever touching a joystick. He has Cerebro, a helmet that amplifies his brain
waves, and in the 90s animated series he floats around in a hover chair.

We had a hoverboard, a hobby EEG headset and a weekend. The joke wrote itself, and then it stopped being a joke.
Our "Cerebro" is an OpenBCI board with gel electrodes. Our hover chair is a split hoverboard we re-flashed by hand.

There is one honest difference. Xavier reads minds. We read signals: where the rider's eyes go, a deliberate
clench of the jaw picked up by the EEG headset, and next, the visual cortex answering a flickering target.
(A fan reference; we are not affiliated with Marvel.)

## Inspiration
A joystick wheelchair assumes a working hand. For people with ALS, a high spinal cord injury or severe cerebral
palsy, that assumption fails, and the options left are slow (sip-and-puff), tiring (head arrays), expensive
(commercial eye-gaze systems) or not independent at all (someone pushes). What many of them keep is eye movement
and a few facial muscles.

So the question we started with was simple: how much of a wheelchair can you run from the neck up, with parts a
student team can buy or borrow, without ever letting the chair move when the rider didn't mean it?

## What it does
The rider sits in a chair bolted to a hoverboard. In front of them is a laptop; taped to the back of its lid is a
phone looking at the room.

- **Look to steer.** Four big arrows on the screen. A webcam follows the rider's eyes; holding a gaze on an arrow
  for 1.5 s starts the chair that way. It keeps moving only while they keep looking. Looking at the centre,
  looking away or closing their eyes for longer than a blink stops it on the next 50 ms tick.
- **Look at a thing to go there.** The phone's view fills the screen with boxes around chairs, tables and people.
  The box under the rider's gaze turns yellow. After 0.3 s it says "CLENCH to confirm".
- **Clench to confirm.** A jaw clench, read by the EEG headset as a burst of muscle activity, turns the box green.
  A glance alone never confirms anything. **[TODO: Vani's live numbers, e.g. "10/10 clenches, 0 false confirms
  while talking".]**
- **Then the chair plans its own way there**, steering around obstacles and stopping 0.7 m short.
  **[TODO: "on the chair" or "in simulation", whichever is true at the freeze.]**
- **Gemini suggests where you probably want to go.** It looks at the room and ranks doors, a table with your
  things or a person above "a chair", so the few choices on screen are the useful ones.

## How we built it

### Following one choice from the eyes to the wheels
The easiest way to explain the system is to follow "go to that chair".

1. **Eyes.** EyeTrax (an open-source webcam gaze library) runs as its own process and sends a gaze point about
   15 times a second over a local socket. Each message carries a version and a type; anything malformed is
   dropped whole. The receiver stamps it with its own clock, so a stale point can never pass as fresh.
2. **Objects.** YOLO finds chairs, tables and people in the phone feed, and ByteTrack keeps each one's ID
   steady from frame to frame. Small objects get a gaze target at least 12% of the screen wide, because webcam
   gaze is only good to a few degrees. A box is entered 2% inside its edge and only left 8% outside it, so a
   wobbling gaze doesn't reset anything.
3. **Confirmation.** The headset's samples are cut into 0.1 s windows. We measure the energy between 40 and 200 Hz
   (where jaw muscles live), skip ±12 Hz around 60/120/180 Hz (mains hum), and fire once when it stays above a
   per-person threshold for 0.3 s. Calibration is 10 s relaxed and three clenches, and it refuses to run if a
   clench isn't at least 3x the relaxed level. A badly attached headset can't confirm anything.
4. **Distance and path.** The object's position in the frame gives a direction; its box height and the camera's
   measured field of view give a distance. A Dynamic Window Approach planner (adapted from PythonRobotics, MIT)
   tries many short arcs ten times a second, throws out any that pass within 0.45 m of an obstacle, and picks the
   one that heads best toward the goal while keeping moving.
5. **Permission.** None of that moves a wheel by itself. A safety state machine (STOPPED, DWELLING, MOVING,
   E_STOP) runs at 20 Hz and decides if the chair may move at all. Its default answer is stop: no input, an old
   input, an unclear input or an exception all mean stop.
6. **Motors.** The laptop sends `C,<seq>,<left>,<right>` lines to an ESP32-S3 every 50 ms, even when stopped. The
   ESP32 turns them into the hoverboard boards' 9-byte frames at 19200 baud, one board per wheel.

### The hoverboard
It's a split hoverboard: two YK187 boards with GD32E235 chips, one per wheel, a 7-cell (about 28 V) battery and
two hub motors. We wanted each board to take speed commands instead of balancing a rider, so we flashed the
open-source RoboDurden firmware onto them ourselves.

That took most of a day. OpenOCD's standard unlock command misread this chip, so we wrote our own. The board has
no crystal, so the prebuilt firmware hung at start-up until we rebuilt it for the internal oscillator. The chip
reports 32 KB of flash and actually has 64 KB. We found the three hall sensors by turning the wheel by hand while
reading the pins through the debugger, and picked their order by flashing twelve test builds and keeping the
smoothest.

### The safety bridge
The ESP32 is deliberately simple and doesn't trust the laptop. If no valid line arrives for 200 ms, it commands
zero. It clamps every speed again. It reads an ultrasonic sensor and refuses forward motion inside 50 cm, but
still allows turning and reversing so the rider is never trapped facing a wall. Below that, the boards stop on
their own 500 ms after their last valid frame, and a kill switch on the battery line cuts power regardless.

### Testing before the chair existed
The chair wasn't built for most of the weekend, so everything ran against stand-ins: a fake serial port for the
ESP32, BrainFlow's fake board with scripted clenches for the headset, and a simulator for the path planner.
**256 automated tests** pass. For the safety rules we did something extra: we deliberately broke a rule (removed
the dwell, let stale data clear an emergency stop, ignored obstacles) and checked that a test failed each time.
Several tests turned out to prove nothing until we did this, and we fixed them.

## Tracks

### Healthcare
This is for people who have lost the hand control a wheelchair assumes. Every design choice starts from what a
rider like that can still do (move their eyes, clench their jaw) and what must never happen to them (the chair
moving when they didn't mean it). That's why confirmation is a deliberate action, why the chair only moves while
you keep choosing, and why every unknown is a stop. We also say plainly what it is not: not a medical device,
tested only by our team.

### Best Hardware Hack
We re-flashed undocumented hoverboard boards from chip unlock to working motor control, found their serial port
by elimination (the obvious pads and the 4-pin plug turned out to be disconnected; it was the 5-pin plug), and
built a layered stop system where the laptop, the ESP32, the boards and a physical switch can each stop the chair
without the others. **[TODO: both wheels driving from the laptop, and the chair carrying a rider on the floor or
wheels-up on a stand.]**

## Challenges we ran into
**The serial port that wasn't there.** The round TX/RX pads and the 4-pin plug looked like the UART. Neither was
connected to the chip (two resistors were never fitted). The link was the 5-pin plug, and even then every byte
came out garbled, because the "ground" pin we used wasn't a solid ground. The ESP32 was reading 60 Hz mains hum.
A wire to the battery's negative fixed it.

**A brain signal that was really the wall socket.** Our first recording seemed to show a huge peak at 15 Hz, the
frequency the rider was looking at. The board was actually sampling at 1000 Hz, not the 250 Hz we assumed, so we
had the frequency axis wrong by 4x: the peak was 60 Hz mains hum. We caught it by checking the timestamps. The
next recording was pinned at the amplifier's limit on every channel, which turned out to be the ear-clip
reference. We stopped trusting any signal we hadn't sanity-checked.

**Our own eye tracker wasn't good enough.** It read left/right well (correlation 0.97 with the target) and up/down
badly (0.74), drifted by up to 0.45 of the screen when the rider moved, and our first calibration model, with 28
terms fitted to 9 dots, memorised noise: 31%, then 5% accuracy. A simpler model got 97% on our test, but in live
use EyeTrax was better, so we switched and kept ours as a fallback.

**Object IDs that wouldn't stay put.** The tracker handed out 296 IDs in four minutes, and every new ID reset the
rider's gaze timer. The bug was ours: we filtered out weak detections before the tracker could use them to keep an
object alive. After the fix it was 4 IDs in 30 seconds.

**A path planner that froze.** In simulation the planner crept 0.4 m toward an obstacle and stopped forever,
because standing still always scored best. Adding a "rotate when stuck" rule fixed it. Then the fastest settings
skimmed obstacles at exactly the safety radius, so we picked slower ones that keep 0.6 m clearance.

**A test suite that could spin the wheels.** When we merged the firmware branch, the test runner started importing
the hardware bench script (its name ended in `_test.py`), and that script opens the serial port and sends motor
commands the moment it loads. It failed harmlessly that time. We excluded hardware folders from the tests before it
could happen with the ESP32 plugged in.

## Accomplishments that we're proud of
- **[TODO: the chair driving from the laptop with a rider, and how many runs in a row.]**
- A rider steered all four directions with only her eyes, and looking away always stopped the chair.
- Undocumented hoverboard boards, re-flashed and taking commands from our own bridge.
- A safety story we can say in one breath: hardware switch, independent 200 ms watchdog, and stop as the default
  answer to anything unclear.

## What we learned
- Measure before believing. The sample rate, the camera's field of view (85.5°, not the 70° we guessed, which had
  every distance 40% too far), the serial pins, the wheel direction: nearly every big bug was an assumption.
- Design around what the sensor is good at. Webcams track left/right far better than up/down, so the interface
  leans on horizontal choices and big targets.
- For a "yes", a jaw clench through an EEG headset is far more dependable than trying to read a thought.
- Small written contracts (one text line to the ESP32, one message for a gaze point) let four people build in
  parallel and swap parts, like replacing our eye tracker with EyeTrax without touching anything else.

## What's next
- Brain-signal (SSVEP) confirmation once electrode contact is reliable. The flicker screen is built and frame-timed.
- Three ultrasonic sensors and wheel odometry, so the planner can see to the sides and know how far it has gone.
- Tests with the people this is for, and with clinicians, before anyone calls it more than a prototype.

## Built with
python, opencv, pygame, ultralytics-yolo, bytetrack, mediapipe, eyetrax, brainflow, openbci-cyton, gemini,
numpy, scipy, esp32-s3, arduino, gd32, robodurden-hoverboard-firmware, openocd, pythonrobotics

## Honest limitations (we'll say these in judging)
Not a medical device; tested only by our team. Gaze tracking needs decent light and a fresh calibration whenever
the laptop moves. The confirmation is a muscle signal, not mind reading. Distances are estimated from the camera
and can be off by 10-20%. **[TODO: driving on the venue floor, or on a stand.]**
