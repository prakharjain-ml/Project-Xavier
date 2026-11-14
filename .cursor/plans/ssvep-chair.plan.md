---
name: SSVEP BCI Wheelchair - master plan
overview: The complete context and the locked, phase-by-phase execution plan for building a brain-controlled wheelchair at HackPrinceton Fall 2026 (Princeton University, Nov 13-15, 2026). Every agent and teammate works from this file. Each phase has a time window tied to the official event schedule, named owners, concrete tasks, a gate that must pass with evidence, and a fallback if it does not.
status: locked v1 (Thu Nov 12). Changes only by team agreement, recorded in PROGRESS.md.
---

# SSVEP BCI Wheelchair: master plan

## 1. Mission and context

### 1.1 The problem
People with high spinal cord injuries, ALS, or severe cerebral palsy often cannot operate a standard joystick
wheelchair. The alternatives they are offered today, such as sip-and-puff switches, head arrays, chin joysticks,
commercial eye-gaze trackers, or a caregiver pushing the chair, are slow, tiring, expensive, depend on some
remaining motor control, or take away independence. Clinical brain-computer interfaces exist, but they are
research systems that cost tens of thousands of dollars and stay in labs. A large group of people can still
move their eyes reliably and focus their attention, even when they cannot move their hands. We want to turn
that ability into independent movement.

### 1.2 What we are building
We are building a low-cost wheelchair that its rider steers with their brain signals, using a technique called
steady-state visually evoked potentials (SSVEP). When a person looks at a light that flickers at a steady
frequency, for example 12 times per second, the visual cortex at the back of the head produces electrical
activity at that same frequency, plus its harmonics. Electrodes on the scalp over the visual cortex can pick
this up. If several targets on a screen each flicker at a different frequency, we can tell which one the
person is looking at by finding which frequency is strongest in their EEG.

The full system has five parts that work together:

1. **The flicker screen.** A laptop screen mounted in front of the rider shows four large arrows (forward,
   back, left, right). Each arrow flickers at its own frequency, timed exactly to the screen's 60 Hz refresh.
   A bar under each arrow fills as the system becomes confident that the rider is looking at it.
2. **The EEG headset.** Wet (gel) electrodes sit over the occipital lobe at positions O1, O2, and if we have
   a spare channel, Oz, with the reference on an earlobe. They connect to an OpenBCI board that streams the
   EEG wirelessly to the laptop through its USB dongle. The BrainFlow library reads the stream in Python.
3. **The decoder.** Python code filters the EEG (band-pass plus a 60 Hz mains notch), looks at the last
   1.5 seconds of signal, scores each target frequency with FFT power and with canonical correlation analysis
   (CCA), and outputs which target won and how confident it is. A second detector watches for the strong
   8 to 13 Hz alpha rhythm that appears when a person closes their eyes, and treats it as a stop request.
4. **The safety controller.** A state machine decides, twenty times per second, what the wheels should do.
   Its default is always STOP. The chair only moves after the rider has held their gaze on one arrow for the
   dwell time (1.5 seconds), and it keeps moving only while that same arrow keeps winning. Looking away,
   closing the eyes, losing the signal, an obstacle, or any software error stops it.
5. **The drive platform.** A hoverboard provides two hub motors and a 36 V battery. A plank carries the
   chair on top of the hoverboard, with casters for stability. The hoverboard's mainboard runs open-source
   field-oriented-control firmware that accepts speed commands over a serial line. A small microcontroller
   (an ESP32) sits between the laptop and the hoverboard as an independent safety bridge: it forwards
   commands, reads an ultrasonic distance sensor, stops the motors on its own if an obstacle is too close,
   and sends zero speed if the laptop goes quiet for more than 200 milliseconds. A physical emergency kill
   switch cuts motor power regardless of any software.

### 1.3 What winning looks like: the Mode 1 demo
Mode 1 is the must-have. It is what we demo to every judge, and nothing else starts until it works. The demo
succeeds when all of the following are true and can be shown live within the two-minute judging slot:

1. A teammate sits in the chair wearing the headset. The four arrows flicker on the screen in front of them.
2. The rider looks at FORWARD. Within about 3 seconds (1.5 s analysis window plus 1.5 s dwell) the dwell bar
   fills and the chair rolls forward at a capped, walking-pace speed.
3. The rider looks LEFT or RIGHT and the chair turns in place in that direction after the dwell.
4. The rider looks away from all arrows: the chair stops within about 1 second.
5. The rider closes their eyes: the chair stops within about 1 second, and stays stopped until a teammate
   re-arms it.
6. An object placed in front of the chair inside the stop distance stops it, even if the rider is still
   looking at FORWARD.
7. The kill switch, pressed by a teammate walking beside the chair, cuts motion instantly.
8. With nobody looking at any arrow, the chair never moves on its own.
9. The whole sequence works three times in a row before we call it done.

### 1.4 Stretch goals, in order, with entry conditions
1. **Mode 2, autonomous target selection.** A webcam on the chair runs YOLO object detection with ByteTrack
   tracking. Up to four detected objects (a door, a person, a table) get their own flickering boxes on the
   camera view. The rider picks one by looking at it, and the chair turns to center it and drives toward it,
   stopping when it gets close or when the ultrasonic sensor trips. This is what qualifies us for the Best
   Physical AI Hack track. Entry condition: the Mode 1 gate has passed by the Saturday 6:00 pm go/no-go.
2. **Caregiver alert.** A small Photon 2.0 messaging agent texts a caregiver whenever the chair enters
   emergency stop. Entry condition: Mode 1 has passed and someone has an idle hour. It is never on the
   critical path.

### 1.5 What we are not building this weekend
We are not building medical-grade accuracy, outdoor driving, user accounts, a cloud backend, a mobile app,
or anything that needs internet during the demo. We are not claiming clinical validity. We will say plainly
in the pitch what works live and what is future work.

## 2. Hardware inventory

Items marked CONFIRM are assumptions that Keshav (who is bringing most of the hardware) must confirm before
Friday. If an assumption is wrong, the related fallback in section 11 applies.

| Item | Details we are planning around | Brought by | Status | Role in the system |
| --- | --- | --- | --- | --- |
| OpenBCI board | Cyton, 8 channels, 250 Hz sampling, RF dongle to laptop. If it is a Ganglion, it is 4 channels at 200 Hz over Bluetooth, which still works | Keshav | CONFIRM model | Reads EEG and streams it to the laptop |
| OpenBCI USB dongle | USB-A, FTDI serial chip, shows up as `/dev/cu.usbserial-*` on macOS | Keshav | CONFIRM | Wireless link from board to laptop |
| Wet electrodes | Gold cup electrodes (or similar) with conductive gel or paste, for O1, O2, Oz, plus reference and bias/ground | Keshav | CONFIRM type and count | Pick up the SSVEP signal |
| Ear clip electrode(s) | For reference (SRB2 on Cyton) on one earlobe and bias/ground on the other | Keshav | CONFIRM | Reference and noise rejection |
| Conductive gel or paste, cotton swabs, alcohol wipes, headband or cap | Enough for many electrode applications across three days | Keshav | CONFIRM quantity | Low-impedance contact through hair |
| Hoverboard | Two brushless hub motors, 36 V (10S) lithium-ion pack, one mainboard (STM32 or GD32) | Keshav | CONFIRM mainboard chip and that it is a single-board model | Drive wheels and power |
| ST-Link V2 programmer | USB-A, connects to the mainboard SWD header to flash firmware | Keshav | CONFIRM | Flashing the open-source firmware |
| Hoverboard firmware | Open-source FOC firmware (EFeru "hoverboard-firmware-hack-FOC"), built for serial (USART) control | Keshav / Pratosh | CONFIRM version and which USART port | Accepts speed commands over serial |
| Plank, chair, casters, mounting hardware | Plank bolted or strapped across the hoverboard foot pads, chair fixed to the plank, casters front and back so the platform cannot tip | Keshav | CONFIRM | The physical chair |
| Emergency kill switch | Latching mushroom button that cuts battery power to the mainboard, rated for the pack current, with an inline fuse | Keshav | CONFIRM it exists and where it cuts | Hardware-level stop |
| ESP32 dev board | 3.3 V logic matches the hoverboard serial port. Fallback: Arduino from the MLH kit with a level shifter or voltage divider on its TX line | Keshav or MLH kit | CONFIRM | Safety bridge, watchdog, ultrasonic reader |
| Ultrasonic distance sensor | HC-SR04 style, 2 to 400 cm range, 5 V; its echo pin needs a voltage divider before it goes into the ESP32 | Keshav or MLH kit | CONFIRM | Obstacle stop |
| Laptop for the demo | Prakhar's MacBook Air M2, built-in display at 60 Hz, USB-C only | Prakhar | Have it | Runs the flicker screen and all Python code |
| USB-C to USB-A adapters or hub | At least two: one for the OpenBCI dongle, one for the ESP32 cable | Prakhar | Must buy or borrow before Friday | Connects USB-A devices |
| Webcam (Mode 2) | Laptop camera, or a Logitech webcam borrowed from the MLH hardware desk | MLH desk | Available at event | Object detection for Mode 2 |
| Multimeter, wire cutters, breadboards, jumper wires | Available from the MLH hardware kit at the event | MLH desk | Available at event | Wiring and debugging |
| Phone | Pixel 9 Pro, slow-motion video for checking flicker timing, hotspot as Wi-Fi backup | Prakhar | Have it | Verification and backup network |

Hardware facts every agent must respect:
- The hoverboard battery is a 36 V lithium-ion pack. It is a fire and shock risk. Nobody works on wiring
  while it is connected, and it never charges unattended.
- The hoverboard mainboard's serial pins are 3.3 V logic. The sideboard connector also carries a higher
  voltage line (around 15 V on common boards). Connecting the wrong wire to the ESP32 will destroy it.
  Keshav identifies every pin with the multimeter before anything is connected.
- The laptop display refresh is 60 Hz, so every flicker frequency must divide 60 by a whole number of frames.

## 3. Software stack

| Layer | Tool | Notes |
| --- | --- | --- |
| Language | Python 3.12 | Virtual environment at `~/venvs/hp26`, outside the repo |
| EEG input | BrainFlow | Same code for the synthetic board (development) and the Cyton (real) |
| Signal processing | numpy, scipy | Butterworth band-pass, IIR notch at 60 Hz, FFT |
| Classification | scikit-learn `CCA` | Canonical correlation against sine/cosine references at f and 2f |
| Flicker screen | pygame | Must run on the main thread on macOS; frame-counted timing |
| Serial to bridge | pyserial | Laptop to ESP32 over USB |
| Bridge firmware | Arduino core for ESP32, Arduino IDE | Watchdog, ultrasonic, hoverboard frame encoding |
| Vision (Mode 2) | OpenCV, Ultralytics YOLO, ByteTrack | Runs on Apple GPU (`mps`) when available |
| Tests | pytest | No hardware in tests; mock serial and synthetic EEG |
| Coding agents | Cursor (main), Claude Code, Codex | See `docs/VIBECODING.md` for models and workflow |
| Version control | Git, GitHub (public repo created Fri 8:00 pm) | One branch per folder, `main` always runs the smoke test |

## 4. Team and ownership

| Person | Background | Owns | Pairs on |
| --- | --- | --- | --- |
| Keshav | Hardware lead, recent hackathon winner, owns the OpenBCI board, first time doing BCI | Headset application and electrode quality, chassis build, firmware flashing, kill switch, sensor wiring | Bridge firmware with Pratosh |
| Pratosh (RIT) | Three-time hackathon winner, robotics research | `motors/` (serial driver, mock, teleop), `firmware/bridge/` (ESP32 sketch), control integration on the real chair | Control state machine with Prakhar |
| Vani (UIUC) | Strong software engineer, internships at Citadel and Amazon, won a Cal Hacks track | `bci/` (acquisition, filters, FFT and CCA decoder, alpha detector), `vision/` for Mode 2 | Calibration analysis with Prakhar |
| Prakhar (Georgia Tech) | First-year ISyE, advanced beginner in Python, second hackathon | `interface/` (flicker screen), `control/` design and tests, `shared/protocol.py`, `docs/`, test checklists, demo video, Devpost, pitch | Learns the decoder by pairing with Vani during calibration |

Ownership above is the proposal we lock at kickoff. If a teammate prefers a different split, we change this
table and AGENTS.md in the first 15 minutes, then never argue about it again.

## 5. Constraints

From the official HackPrinceton F26 onsite packet and schedule:
- Hacking runs from Friday Nov 13 at 8:00 pm to Sunday Nov 15 at 8:00 am. The Devpost deadline is 8:00 am
  Sunday and the packet calls it a hard deadline (the schedule PDF says 8:15 am; we plan for 8:00).
- The project must link a public GitHub repository created between Nov 13 and Nov 15. All hacking happens
  within the 36 hours. Planning documents, rules and agent configuration are prepared beforehand; project
  source code is not.
- We enter exactly one main track (Healthcare) and any number of special tracks. Each special track adds a
  judging visit.
- Judging is 9:30 am to 2:30 pm Sunday at an assigned location announced on Discord after the deadline. The
  in-person demo is required and must not exceed 2 minutes, even if we upload a video.
- Teams have at most 4 members. Wi-Fi for visitors is `puvisitor`.
- There are no designated sleeping areas; people rest in classrooms marked as Hacker Spaces. Workshop rooms
  cannot be used for hacking during workshop times.

Safety and venue constraints we set ourselves:
- **Blocking question for the organizers, ask on Discord tonight:** are we allowed to operate a
  hoverboard-based motorized chair with a 36 V lithium-ion battery inside JRR, LAS or Robertson Hall for
  testing and judging, and is there an area we should use? Many campuses restrict hoverboards indoors. If the
  answer is no, the demo becomes the chair on a stand with wheels spinning off the ground, and we plan for
  that from Phase 4 on.
- Nobody rides the chair until the wheels-off-the-ground test has passed, the kill switch has been tested,
  and a spotter is walking beside it.
- Before anyone looks at the flicker screen, we ask whether they have photosensitive epilepsy or a history
  of seizures triggered by flashing lights.

Laptop constraints:
- One laptop (Prakhar's M2 MacBook Air) runs the flicker screen, BrainFlow, the decoder and control, because
  the timing of the flicker and the EEG must share a clock. Its screen is the flicker display.
- During the demo, nothing on that laptop needs the internet.

## 6. Locked decisions

These were open questions. They are now decided so that nobody waits on them. Each has a reason and a
trigger that would reopen it.

| ID | Decision | Reason | Reopen only if |
| --- | --- | --- | --- |
| D1 | **Hold-to-move.** The chair moves only while the same arrow keeps winning after the dwell; any change, loss of confidence or stale data stops it | Safest behaviour for a rider who may not be able to react physically | Calibration shows the winning target flickers on and off so often that motion is jerky; then we add a short 0.5 s hold-over, never more |
| D2 | **Starting frequency set: FORWARD 6.67 Hz, LEFT 8.57 Hz, RIGHT 12 Hz, BACK 15 Hz** (9, 7, 5 and 4 frames per cycle at 60 Hz) | No pair where one is double another, all exact at 60 Hz, all inside the band where SSVEP is strong | Phase 3 calibration shows a better set on our real riders; the decision is made by the data by Saturday 11:00 am |
| D3 | **One Python process.** pygame owns the main thread; acquisition and decoding, control, and serial writing run on separate threads connected by queues. Vision (Mode 2) runs as a separate process and sends JSON over localhost UDP | macOS requires pygame on the main thread; one process keeps the clocks aligned and the code simple | Frame drops appear that we can trace to the Python threads |
| D4 | **Laptop to ESP32 safety bridge to hoverboard.** The laptop sends simple text commands over USB serial; the ESP32 encodes hoverboard frames, runs a 200 ms watchdog, and enforces the ultrasonic stop on its own | Two independent safety layers below the laptop; the ESP32's 3.3 V logic matches the hoverboard | We have no ESP32; then an Arduino with a level shifter does the same job |
| D5 | **Demo laptop and display: Prakhar's MacBook Air screen, mounted at eye level on the chair** | Known 60 Hz refresh; one machine for timing | The mount is unstable; then a table stand in front of the chair |
| D6 | **Electrode montage: O1, O2, Oz (if a channel is free), reference on the left earlobe, bias on the right earlobe** | Standard SSVEP placement over the visual cortex | The board model or electrode count differs; Keshav adapts and records it in PROGRESS.md |
| D7 | **Decoder default: CCA with references at f and 2f; FFT power kept as a baseline and fallback** | CCA is usually more robust for SSVEP with few channels and handles harmonics | Phase 3 shows FFT is better on our data |
| D8 | **Rider for demos is a teammate, never a judge or stranger** | Safety and photosensitivity; a trained rider gives a reliable demo | Never |

## 7. System design in one page

The rider looks at an arrow. The OpenBCI board samples the occipital electrodes at 250 Hz and streams to the
laptop. Every 0.25 seconds, the decoder takes the most recent 1.5 seconds of samples, filters them (band-pass
roughly 5 to 40 Hz, notch at 60 Hz), and computes a score for each of the four frequencies. The winner and a
confidence value become an `Intent`. The alpha detector compares 8 to 13 Hz power against the rider's
eyes-open baseline and raises a `StopRequest` when the eyes close.

The control loop runs at 20 Hz and always emits a `MotorCommand`. It follows the states in `docs/SAFETY.md`:
STOPPED, DWELLING, MOVING and E_STOP. The command goes to the serial writer, which sends a line of text to the
ESP32 every 50 ms. The ESP32 clamps the speed, checks the ultrasonic distance, and sends the hoverboard firmware
its 8-byte command frame. If the ESP32 hears nothing from the laptop for 200 ms, it commands zero. The kill
switch cuts power to the motors no matter what any software does.

Details: `docs/ARCHITECTURE.md` (threads, folders, latency budget), `docs/INTERFACES.md` (every message, the
serial formats, constants), `docs/SAFETY.md` (states, transitions, test protocol).

## 8. Timeline at a glance

All times are Eastern. Meals and talks come from the official schedule. The two times that never move are
the **Saturday 6:00 pm Mode 2 go/no-go** and **Devpost submitted by Sunday 7:15 am**.

| Window | Phase | Who is awake and working | Event schedule around it |
| --- | --- | --- | --- |
| Thu night to Fri 6:30 pm | Phase 0: Prep | Everyone, remotely, then on arrival | Check-in 4:30 to 6:30 pm, dinner 5:00 to 6:00 pm |
| Fri 6:30 to 8:00 pm | (Opening ceremony) | Everyone attends | Opening with Stephen Wolfram |
| Fri 8:00 to 10:00 pm | Phase 1: Kickoff and walking skeleton | Everyone | Hacking starts 8:00 pm |
| Fri 10:00 pm to Sat 2:00 am | Phase 2: Components on fake data, plus a first real-signal check | Everyone | Geoguessr 10:30 pm, midnight cereal bar |
| Sat 2:00 to 6:00 am | Phase 2 continues (hardware) | Keshav and Pratosh; Prakhar and Vani sleep | |
| Sat 6:00 to 11:00 am | Phase 3: Real signal and calibration | Prakhar and Vani; Keshav and Pratosh sleep 6:00 to 10:00 am | Breakfast 9:00 to 10:00 am |
| Sat 11:00 am to 6:00 pm | Phase 4: Mode 1 integration on the real chair | Everyone | Lunch 12:00 to 1:00 pm; Technical Storytelling 1:00 to 2:00 pm (Prakhar attends) |
| Sat 6:00 pm | Go/no-go | Everyone | Dinner 6:00 to 7:00 pm |
| Sat 7:00 pm to Sun 1:00 am | Phase 5A (Mode 2) or Phase 5B (hardening) | Everyone | Trivia 9:30 pm, midnight snacks |
| Sun 1:00 to 2:00 am | Phase 6: Feature freeze and footage | Everyone | |
| Sun 2:00 to 7:15 am | Phase 7: Ship (video, Devpost, rehearsal) | Prakhar sleeps 2:00 to 5:00 am; Vani 4:00 to 7:00 am; Keshav and Pratosh 4:00 to 7:30 am | Hacking ends 8:00 am |
| Sun 9:30 am to 2:30 pm | Phase 8: Judging | Everyone | Breakfast 8:00 to 9:00 am, closing ceremony 2:30 to 4:00 pm |

## 9. How every phase runs

1. At the start of the phase, the owner of each folder opens Cursor in Plan mode, attaches this file and the
   folder's README, and asks for a plan for that phase and that folder only. They review it, edit it, and
   save it to the workspace so it gets Cursor's Build button.
2. Work happens in the Cursor Agents Window, with one agent per folder, each in its own git worktree, so no
   two agents ever edit the same file.
3. Every task ends with evidence: the exact command run and its real output, a passing test, a saved plot, or
   a phone video. "It should work" is never accepted.
4. Before merging to `main`, a different model reviews the diff with `/review-diff`, and
   `python tools/smoke.py` must pass.
5. At the end of the phase, `/phase-gate` checks the gate below and records the verdict in PROGRESS.md.
6. If a gate fails at its deadline, we take the fallback written for it, record the decision, and move on.
   We do not extend a phase silently.
7. Team syncs happen at fixed times: Fri 10:00 pm, Sat 2:00 am, Sat 11:00 am, Sat 3:00 pm, Sat 6:00 pm,
   Sat 10:00 pm, Sun 1:00 am. Each sync is 10 minutes: gate status, blockers, next three hours.

---

## Phase 0: Prep (Thursday night to Friday 6:30 pm)

**Objective.** Arrive at kickoff with every laptop set up, every agent loaded with this context, every hardware
assumption confirmed, and the venue question answered, so that the first hour of hacking is spent building.

**Allowed in this phase.** Installing tools, creating accounts, learning, writing and editing these planning
documents and agent rules, and practice exercises in a throwaway folder. **Not allowed:** project source code
or the project repository.

| ID | Owner | Task | Output | Time |
| --- | --- | --- | --- | --- |
| 0.1 | Prakhar | Post the venue question (section 5) in the HackPrinceton Discord and tag an organizer | Written answer, pasted into PROGRESS.md | 10 min tonight |
| 0.2 | Prakhar | Send Keshav the CONFIRM list from section 2 and section 12; get answers | Every CONFIRM resolved or marked as a known risk | Tonight |
| 0.3 | Everyone | Install the toolchain: Cursor, Python 3.12, `~/venvs/hp26` with numpy, scipy, matplotlib, scikit-learn, brainflow, pyserial, pygame, opencv-python, ultralytics, pytest; Arduino IDE with ESP32 board support for Pratosh and Keshav | Import test passes on each laptop | 45 min each |
| 0.4 | Everyone | Open this workspace in Cursor and ask "What is the default motor command, and which folder may you edit?" | Agent answers STOP and names only the folder given | 5 min each |
| 0.5 | Prakhar | Practice in a throwaway folder: frame-counted pygame flicker at 60 Hz, FFT of a synthetic 12 Hz signal, YOLO on the webcam. Nothing from this folder enters the repo | Understanding, plus notes in plain text | 75 min tonight |
| 0.6 | Prakhar | Read `docs/SAFETY.md` and `docs/INTERFACES.md` closely and write down questions for kickoff | Question list | 30 min |
| 0.7 | Prakhar | Buy or borrow two USB-C to USB-A adapters | Adapters in the bag | Before check-in |
| 0.8 | Keshav | Pack the hardware list in section 2, including spare gel, the ST-Link, and the kill switch | Packed | Before driving |

**Gate 0.** All four laptops pass the import test and the rules test, the venue question has an answer, and
every CONFIRM item is answered or listed as a risk. Evidence: one line per person in PROGRESS.md.

**Fallback.** If the venue says no to riding, Phase 4 targets a wheels-off-the-ground demo on a stand, and the
pitch shows a recorded clip of riding somewhere permitted, if one exists.

---

## Phase 1: Kickoff and walking skeleton (Friday 8:00 to 10:00 pm)

**Objective.** By 10:00 pm the whole pipeline exists end to end on fake data: synthetic EEG goes in, a stub
decoder emits Intents, the real state machine skeleton emits commands, and a mock motor driver prints them.
At the same time, the hardware track starts flashing the firmware, because it is the longest hardware task.

**Entry condition.** The opening ceremony is over and all four of us are at one table with power.

| ID | Owner | Task | Output | Time |
| --- | --- | --- | --- | --- |
| 1.1 | Prakhar | Create the public GitHub repo, commit this workspace as the first commit, add the three collaborators | Repo URL in team chat; everyone has cloned it | 8:00 to 8:15 |
| 1.2 | Everyone | Fifteen-minute walkthrough of sections 1, 6 and 9 of this plan, and of `docs/INTERFACES.md`; confirm the ownership table | Ownership confirmed in AGENTS.md | 8:15 to 8:30 |
| 1.3 | Prakhar | With an agent, generate `shared/protocol.py` from `docs/INTERFACES.md`: frozen dataclasses for Intent, StopRequest, MotorCommand, ControlStatus and TargetSet, the Target and State enums, and every constant | Module imports cleanly; a test checks every constant against the doc | 8:30 to 9:00 |
| 1.4 | Vani | `tools/fake_eeg.py`: synthetic multi-channel EEG at 250 Hz with a chosen SSVEP frequency and its harmonic, pink noise, an alpha burst on demand, and 60 Hz hum | A saved plot showing the target peak after filtering | 8:30 to 9:15 |
| 1.5 | Pratosh | `motors/mock_serial.py` and a stub `motors/driver.py` that accept MotorCommands and print what would be sent | Mock driver test passes | 8:30 to 9:15 |
| 1.6 | Prakhar | Skeleton `control/state_machine.py` with the four states and STOP as the default branch | Unit test: no input produces STOP | 9:00 to 9:30 |
| 1.7 | Vani | `tools/smoke.py` wiring fake EEG, a stub decoder, the control skeleton and the mock driver into one run | Prints a command sequence that starts and ends with STOP, exits with code 0 in under 10 seconds | 9:15 to 9:45 |
| 1.8 | Keshav | Hardware track: open the hoverboard, identify the mainboard chip and the SWD and USART pins with the multimeter, photograph everything, start flashing the FOC firmware with the ST-Link | Photos and pin map in `firmware/README.md`; flash attempt started | 8:30 to 10:00 |

### Phase 1 packaging & integration note
In Task 1.3 (`8:30 to 9:00 pm`), Prakhar also creates a minimal `pyproject.toml` (`pip install -e .` into `~/venvs/hp26`) and package `__init__.py` files so `python tools/smoke.py` imports `shared`, `control`, `bci`, and `motors` cleanly from the repo root. In Task 1.4 (`tools/fake_eeg.py`), Vani may use a minimal inline scipy filter check for the Phase 1 plot before `bci/filters.py` lands in Task 2.2. For Tasks 3.5 and 3.6 (`9:30 to 10:45 am` Saturday), Vani and Prakhar pull forward the screen-only (`--mock`) loop of `app.py` so live accuracy and alpha tests run before `11:00 am` hardware integration.

**Gate 1 (10:00 pm sync).** `python tools/smoke.py` runs on `main` and prints a STOP-first, STOP-last command
sequence. Evidence: the command and its output in PROGRESS.md.

**Fallback.** If interface debates are still running at 9:15 pm, Prakhar decides, records the decision, and the
team revisits it at the 2:00 am sync.

---

## Phase 2: Components on fake data, plus a first real-signal check (Friday 10:00 pm to Saturday 6:00 am)

**Objective.** Each folder becomes a real, tested component that works without hardware. In the middle of the
phase, we put the headset on once to prove that a real SSVEP peak appears, so that the riskiest unknown is
tested on night one instead of Saturday afternoon.

**Entry condition.** Gate 1 passed.

### bci/ (Vani)
| ID | Task | Done when | Time |
| --- | --- | --- | --- |
| 2.1 | `bci/acquire.py`: BrainFlow wrapper with `--synthetic` (BoardIds.SYNTHETIC_BOARD) and `--cyton --port`, reading sampling rate and EEG channel numbers from BrainFlow | Streams 10 s from the synthetic board and prints shape and rate | 10:00 to 10:45 pm |
| 2.2 | `bci/filters.py`: zero-phase Butterworth band-pass (about 5 to 40 Hz) and 60 Hz notch | Test: a 12 Hz sine survives, 60 Hz hum is attenuated by at least 20 dB | 10:45 to 11:15 pm |
| 2.3 | `bci/ssvep.py`: FFT-power scorer and CCA scorer, both with f and 2f, same interface | Test: each of the four frequencies is recovered from fake EEG; a 6 Hz signal does not score as 12 Hz | 11:15 pm to 12:30 am |
| 2.4 | `bci/decoder.py`: 1.5 s sliding window, 0.25 s step, margin-based confidence, NONE below threshold | At least 95% of windows correct on fake EEG at moderate noise; pure noise returns NONE most of the time | 12:30 to 1:30 am |
| 2.5 | `bci/alpha.py`: eyes-closed detector using 8 to 13 Hz power against a rolling eyes-open baseline | Fake alpha burst triggers a StopRequest within 1 s; flicker at 8.57 or 12 Hz alone does not | 1:30 to 2:00 am |

### interface/ (Prakhar)
| ID | Task | Done when | Time |
| --- | --- | --- | --- |
| 2.6 | `interface/flicker.py`: four arrows on black, each toggling by frame count with the on/off split from the rules (9 = 5 + 4, 7 = 4 + 3, 5 = 3 + 2, 4 = 2 + 2), live FPS and dropped-frame counter | 60 FPS for 60 s with zero dropped frames, fullscreen | 10:00 to 11:15 pm |
| 2.7 | Photosensitivity warning start screen; flicker begins only after SPACE | Screen shows, SPACE starts, ESC quits | 11:15 to 11:30 pm |
| 2.8 | Dwell bars and selected-target highlight driven by `ControlStatus` from a queue, without blocking the loop | Fake ControlStatus stream animates the bars while FPS stays at 60 | 12:00 to 1:00 am |
| 2.9 | Slow-motion phone video of each target (240 fps): count phone frames per flicker cycle and compare with the expected value | Measured frequencies within 2% of target; video saved to the team drive | 1:00 to 1:30 am |

### First real-signal check (Prakhar, Vani, Keshav)
| ID | Task | Done when | Time |
| --- | --- | --- | --- |
| 2.10 | Keshav applies electrodes at O1, O2 (and Oz) on Prakhar, checks impedance in the OpenBCI GUI, aiming for under about 20 kOhm. Prakhar stares at a single fullscreen 12 Hz flicker from 2.6 for 30 s while Vani watches the GUI's FFT plot, then 30 s with eyes closed | A visible peak near 12 Hz (and 24 Hz) while looking, and a clear alpha bump with eyes closed. Screenshot saved | 11:30 pm to 12:00 am |

If there is no 12 Hz peak, we fix contact (more gel, part the hair, check the reference clip) and repeat once.
If there is still nothing by 12:30 am, we try another wearer, because SSVEP strength varies between people.
This result decides who the demo rider is. Vani pauses task 2.3 for this half hour and resumes it afterwards.

### control/ (Prakhar design, Pratosh review)
| ID | Task | Done when | Time |
| --- | --- | --- | --- |
| 2.11 | Full state machine from `docs/SAFETY.md`: STOPPED, DWELLING, MOVING, E_STOP; stale-Intent timeout; operator re-arm | Every transition row in SAFETY.md has a passing table-driven test | Prakhar 1:30 to 2:00 am; Pratosh finishes and reviews 3:00 to 3:45 am together with 2.12 |
| 2.12 | `control/mapping.py`: target to wheel speeds with MAX_SPEED clamp; random low-confidence fuzz test | 1,000 random low-confidence Intents never produce motion | Pratosh, 3:00 to 3:45 am |

### motors/ and firmware/bridge/ (Pratosh, Keshav)
| ID | Task | Done when | Time |
| --- | --- | --- | --- |
| 2.13 | Firmware flashed and both wheels spin on the bench (wheels off the ground) from the FOC firmware's own test or a USB-serial adapter | Video of both wheels spinning both directions at low speed | Keshav with Pratosh, 10:00 pm to 12:00 am |
| 2.14 | `firmware/bridge/bridge.ino` for the ESP32: parse laptop command lines, encode hoverboard frames, 200 ms watchdog to zero, read the ultrasonic sensor, local obstacle stop, report distance back | Bench test: unplugging the laptop USB stops the wheels within 200 ms; a hand in front of the sensor stops them | Pratosh and Keshav, 12:00 to 3:00 am |
| 2.15 | `motors/driver.py` (laptop side): sends command lines at 20 Hz, reads distance replies, zero on timeout; `motors/teleop.py` for humans only | Mock tests pass; human-run teleop drives the wheels on the bench | Pratosh, 3:45 to 5:45 am |
| 2.16 | Chassis: plank mounted on the hoverboard, chair fixed to the plank, casters installed, kill switch wired in the battery line and tested | Platform rolls by hand without tipping; kill switch cuts power on the bench | Keshav, 3:00 to 6:00 am |

**Sleep.** Prakhar and Vani sleep from 2:00 to 6:00 am, after writing their handoffs with `/handoff`. Keshav
and Pratosh keep the hardware track moving.

**Gate 2 (6:00 am handover).** Each software folder's tests pass on `main`; the smoke test still passes; the
real-signal check showed a peak; the wheels spin under bridge control on the bench. Evidence in PROGRESS.md.

**Fallbacks.** If the firmware cannot be flashed by 2:00 am, we switch to whatever alternative motor controller
Keshav has (confirm in Phase 0), and the plan continues with a different `firmware/` target. If no real SSVEP
peak appears on any wearer, we keep building on fake data and attack signal quality first thing in Phase 3.

---

## Phase 3: Real signal and calibration (Saturday 6:00 to 11:00 am)

**Objective.** Measure how well our decoder works on real heads, choose the final frequencies, window length,
threshold and scoring method from data, and confirm the eyes-closed stop is reliable. This is the riskiest
phase, so it runs first thing in the morning with fresh people.

**Entry condition.** Gate 2 passed, or at least the bci and interface parts of it.

| ID | Owner | Task | Output | Time |
| --- | --- | --- | --- | --- |
| 3.1 | Vani | `tools/record.py`: guided recording session that shows one target at a time for 20 s with a 5 s rest, saves raw EEG with labels to `data/raw/` (gitignored) | One labeled file per session | 6:00 to 6:45 |
| 3.2 | Rider chosen in 2.10 (Prakhar by default), Vani operating | Apply electrodes, check impedance, then record two full sessions: four targets, eyes-closed and rest | Two sessions saved | 6:45 to 7:45 |
| 3.3 | Vani | `tools/analyze.py`: offline accuracy per target for FFT and CCA at windows of 1.0, 1.5 and 2.0 s; confusion matrix; information transfer rate. Use Cursor `/visualize` for the charts | Table and charts in `docs/calibration.md` | 7:45 to 9:00 |
| 3.4 | Prakhar, Vani | Choose the final set: frequencies (keep D2 unless the data says otherwise), window, confidence threshold, FFT or CCA | Decision recorded in PROGRESS.md and in `shared/protocol.py` | 9:00 to 9:30 |
| 3.5 | Prakhar | Live closed-loop test on screen only (no motors): rider looks at each target in turn; record hits, misses, time to select | Live accuracy and mean time to select | 9:30 to 10:15 |
| 3.6 | Prakhar | Alpha stop test: rider stares at each target for 30 s (must not trigger stop), then closes eyes five times (must trigger every time) | Zero false stops, five out of five true stops | 10:15 to 10:45 |
| 3.7 | Vani | Record a clean 60-second screen capture of live decoding for the demo video, in case later phases break | Clip saved | 10:45 to 11:00 |

**Gate 3 (11:00 am sync).** Live four-target accuracy is at least 80% with the chosen window, mean time to
select is under 4 s, rest produces NONE at least 90% of the time, and the alpha test passes. Evidence:
`docs/calibration.md` plus the numbers in PROGRESS.md.

**Fallback ladder, decided at 11:00 am.** If four targets fall short, drop to three (FORWARD, LEFT, RIGHT, with
BACK removed). If three fall short, drop to two (FORWARD and a TURN target). If accuracy is still low, lengthen
the window to 2 s and accept slower selection. Each step down is recorded, and the demo script changes with it.

---

## Phase 4: Mode 1 integration on the real chair (Saturday 11:00 am to 6:00 pm)

**Objective.** Connect the live decoder, the state machine, the laptop serial driver, the ESP32 bridge and the
hoverboard, and reach the full Mode 1 demo described in section 1.3.

**Entry condition.** Gate 3 passed (or a fallback rung chosen) and the chassis from 2.16 is complete.

| ID | Owner | Task | Output | Time |
| --- | --- | --- | --- | --- |
| 4.0 | Pratosh, Keshav | Mount the ESP32, ultrasonic sensor, kill switch and laptop holder on the chair; human-run teleop with nobody on board, wheels off the ground | Teleop drives and stops through the bridge on the finished chassis | 10:30 am to 12:00 pm |
| 4.1 | Vani, Prakhar | `app.py`: wire every part with queues per D3; flags `--synthetic --mock` and `--cyton --serial PORT` | Full app runs with fake EEG and mock motors | 11:00 am to 12:00 pm |
| 4.2 | Pratosh, Keshav | Wheels-off-the-ground test with the full app and a real rider; kill switch in Keshav's hand | Video: wheels respond to gaze and stop on look-away and eyes-closed | 1:00 to 2:00 pm |
| 4.3 | Everyone | First floor test at minimum speed in the permitted area: clear 3 m space, Keshav walking beside with the kill switch, Pratosh at the laptop | Chair drives forward and stops correctly | 2:00 to 3:00 pm |
| 4.4 | Pratosh, Prakhar | Tune dwell time, speed cap and turn speed for smooth, safe movement; log every decision with timestamps | Tuned constants committed with a note on why | 3:00 to 4:30 pm |
| 4.5 | Keshav | Ultrasonic test: obstacle at the stop distance stops the chair every time, from forward motion | Five out of five stops on video | 4:30 to 5:00 pm |
| 4.6 | Everyone | Run the full section 1.3 demo three times in a row, timed, with the planned rider | Three passes recorded | 5:00 to 6:00 pm |

Prakhar attends the Technical Storytelling talk (1:00 to 2:00 pm) because he owns the pitch, but only if he is
not the rider for 4.2. If he is the rider, he skips the talk; the chair test matters more.

**Gate 4 (6:00 pm go/no-go).** The section 1.3 demo works three times in a row. If yes, we go to Phase 5A. If
no, we go to Phase 5B. This decision is not extended.

---

## Phase 5A: Mode 2 autonomous selection (Saturday 7:00 pm to Sunday 1:00 am), only if Gate 4 passed

**Objective.** Add camera-based targets so the rider can choose a real object and the chair drives to it.

| ID | Owner | Task | Done when | Time |
| --- | --- | --- | --- | --- |
| 5A.1 | Vani | `vision/detect_track.py`: YOLO plus ByteTrack on the webcam, top four stable tracks, sends TargetSet as JSON over localhost UDP | Track IDs stable for 10 s while objects move; FPS logged | 7:00 to 9:00 pm |
| 5A.2 | Prakhar | Interface mode that draws the camera feed with a flickering box on each tracked object, using the four calibrated frequencies | Boxes follow objects at 60 FPS | 8:00 to 10:00 pm |
| 5A.3 | Vani, Pratosh | `vision/servo.py` and a control mode that turns to center the chosen box, drives while centered, stops when the box is large enough or the ultrasonic trips; lost track means STOP | Chair approaches a chosen object and stops, wheels off the ground first | 10:00 pm to 12:30 am |
| 5A.4 | Prakhar | Optional, only if idle: Photon messaging agent texts a caregiver on E_STOP | One real text received | Any idle hour |
| 5A.5 | Keshav | Keep Mode 1 healthy while Mode 2 is built: cable strain relief, electrode comfort for long sessions, battery level checks | Mode 1 still passes a quick run at 10:00 pm and 1:00 am | 7:00 pm to 1:00 am |

**Gate 5A.** The chair drives to a chosen object and stops in two out of three tries. This is what lets us
enter Best Physical AI Hack. If it is not reliable by 1:00 am, Mode 2 is shown only as a screen demo and we do
not enter that track.

## Phase 5B: Hardening (same window), if Gate 4 failed

**Objective.** Make the demo we have reliable instead of adding features.

| ID | Owner | Task |
| --- | --- | --- |
| 5B.1 | Everyone | List the failures from the Gate 4 attempts and fix the most common one first |
| 5B.2 | Vani, Prakhar | Step down the fallback ladder from Phase 3 if accuracy is the problem |
| 5B.3 | Keshav | Improve electrode contact and cable strain relief if signal drops during motion |
| 5B.4 | Prakhar | Prepare the honest fallback demo: live decoding on screen with the chair responding on a stand |

---

## Phase 6: Feature freeze and footage (Sunday 1:00 to 2:00 am)

**Objective.** Stop adding things and capture the best version while it works.

| ID | Owner | Task |
| --- | --- | --- |
| 6.1 | Everyone | Freeze at 1:00 am: only demo-critical bug fixes after this point, each reviewed |
| 6.2 | Pratosh | Tag `demo-ok-final` on `main` |
| 6.3 | Prakhar, Keshav | Film demo footage: two full Mode 1 runs from two angles, close-ups of the screen and the dwell bars, the eyes-closed stop, the obstacle stop, and Mode 2 if it works |
| 6.4 | Vani | README finished: what it does, how to run, hardware list, honest limitations, team |

---

## Phase 7: Ship (Sunday 2:00 to 7:15 am)

**Objective.** Submit a complete Devpost with a video by 7:15 am, then rehearse.

| ID | Owner | Task | Time |
| --- | --- | --- | --- |
| 7.1 | Prakhar | Sleep | 2:00 to 5:00 am |
| 7.2 | Vani | Draft the Devpost text from `docs/PRD.md` and PROGRESS.md: inspiration, what it does, how we built it, challenges, accomplishments, what we learned, what is next | 2:00 to 4:00 am |
| 7.3 | Keshav, Pratosh | Charge the hoverboard battery while awake and unplug it before sleeping (never charge it unattended); charge laptops; pack and label everything for judging; then sleep | 2:00 to 4:00 am, sleep 4:00 to 7:30 am |
| 7.3b | Vani | Sleep | 4:00 to 7:00 am |
| 7.4 | Prakhar | Edit the 2-minute video from the Phase 6 footage, upload to YouTube as unlisted, add the link | 5:00 to 6:30 am |
| 7.5 | Prakhar | Finalize the Devpost: Healthcare as the one main track, Best Hardware Hack, Best Physical AI Hack only if Gate 5A passed; add all four Discord usernames; link the repo | 6:30 to 7:00 am |
| 7.6 | Prakhar | **Submit by 7:15 am**, then confirm the submission shows as complete | 7:15 am |
| 7.7 | Prakhar, Vani | Rehearse the 2-minute pitch twice with a judge-style interruption (`docs/DEMO.md`) | 7:15 to 8:00 am |

---

## Phase 8: Judging (Sunday 9:30 am to 2:30 pm)

**Objective.** Give every judge a working live demo and a clear, honest two-minute story.

| ID | Owner | Task |
| --- | --- | --- |
| 8.1 | Keshav | Kit check by 9:15 am: charged laptop and hoverboard, gel, electrodes, kill switch, spare cables, adapters, photosensitivity warning card |
| 8.2 | Keshav | Apply electrodes to the rider 15 minutes before the first judge; re-check impedance between visits |
| 8.3 | Prakhar | Lead every judge visit: problem in one sentence, live demo, safety, what we learned, what is next |
| 8.4 | Everyone | Each person can explain their own folder in one minute if asked |
| 8.5 | Prakhar | Keep a running list of judge questions and our answers, for the post-event reflection |

---

## 10. Operating rhythm and agent use

- Each person runs their own Cursor agents in their own folder. Default models: Fable 5.2 at default effort for
  hard reasoning (decoder, state machine, firmware debugging), a cheaper everyday model for routine code, and a
  different model family for every review. Details in `docs/VIBECODING.md`.
- Every agent session starts from AGENTS.md, this plan's current phase, and the owner's PROGRESS.md section.
- When an agent runs out of quota, the owner runs the five-minute switch routine in `docs/VIBECODING.md`.
- Hardware commands are always run by a human. The project hook asks for confirmation on any command that
  touches a serial port, the EEG board or the motors.

## 11. Risk register

| Risk | Likelihood | Early warning | Response |
| --- | --- | --- | --- |
| Venue forbids riding the chair indoors | Medium | Organizer answer to 0.1 | Demo on a stand with wheels spinning; recorded clip if riding happens elsewhere |
| Weak or no SSVEP signal on our riders | Medium | Task 2.10 shows no peak | Better contact, another rider, fewer targets, longer window |
| Flicker frames drop on the laptop | Low to medium | FPS counter below 60 | Fullscreen, close other apps, fewer targets, simpler drawing |
| Hoverboard firmware will not flash or the board is incompatible | Medium | 2.13 not done by midnight | Alternative motor controller if available; otherwise demo on a stand |
| Wrong pin connected to the ESP32 | Low, high impact | Pin map not written down | Multimeter-verified pin map in `firmware/README.md` before any connection |
| Chair tips or moves unexpectedly | Low, high impact | Any uncommanded motion in testing | Stop all testing, log it, fix, repeat the wheels-off test first |
| Electrodes dry out or shift during demos | Medium | Impedance rising between judge visits | Re-gel between visits; headband over the electrodes |
| Agents run out of quota | Medium | Usage warnings | Switch model or agent with the handoff routine |
| Venue Wi-Fi is slow | High | Slow git pulls | Phone hotspot; nothing at demo time needs internet |
| Team exhaustion causes careless mistakes | High by Sunday | Repeated small errors | Keep the sleep shifts; no motor testing by anyone who has not slept |

## 12. Open questions to close before Friday

| Question | Who answers | Deadline |
| --- | --- | --- |
| Can we ride a hoverboard-based chair indoors at the venue? Where? | Organizers on Discord | Fri noon |
| Which OpenBCI board exactly, and how many electrodes and ear clips? | Keshav | Thu night |
| Gel or paste, and how much? | Keshav | Thu night |
| Which hoverboard mainboard chip, single board or split boards? Has it been flashed before? | Keshav | Thu night |
| Do we have an ST-Link V2 and an ESP32? If not, which Arduino? | Keshav | Thu night |
| What is the kill switch, and does it cut battery power to the mainboard? | Keshav | Thu night |
| Which ultrasonic sensor? | Keshav | Thu night |
| Plank, chair and casters: built already, or built at the event? | Keshav | Thu night |
| Does everyone agree with the ownership table in section 4? | Everyone | Fri 8:30 pm |
