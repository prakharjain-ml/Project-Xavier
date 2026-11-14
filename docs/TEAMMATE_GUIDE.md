# Teammate Guide: What We Are Building, Why, and How We Ship

> **Status (Sat Nov 14).** This document describes the original SSVEP plan. What exists today: the rider looks at an
> object or arrow on the laptop screen (webcam gaze), confirms by dwell or a jaw clench read through the OpenBCI
> headset, and the chair drives through the ESP32 bridge. Only the flicker screen of the SSVEP plan was built: there
> is no SSVEP decoder and no closed-eyes (alpha) detector. See `docs/PROJECT_CONTEXT.md` and `PROGRESS.md`.
> Hardware facts below that are out of date: the pack is 7S, about 28 V (not 36 V); frames to the boards are 9 bytes;
> the Cyton gives 250 Hz on the dongle (about 1000 Hz on the Wi-Fi shield); `tools/smoke.py` does not exist.

This guide is for you (Prakhar) as a teammate on the HackPrinceton Fall 2026 SSVEP Wheelchair team. It explains the whole project in plain English: why it matters, how every part works together, what you own, and everything we must submit by Sunday morning.

---

## 1. Why we are doing this

People with ALS, high spinal cord injury, or severe cerebral palsy often cannot use a standard hand joystick to drive a power wheelchair. Today's alternatives force hard trade-offs:

- **Sip-and-puff straws, chin joysticks, and head switches** are tiring, slow, and still require remaining muscle control in the neck or mouth.
- **Commercial eye-gaze trackers** cost thousands of dollars, struggle in changing indoor or bright lighting, and need frequent per-user camera calibration.
- **Caregiver push control** takes away personal independence.
- **Clinical brain-computer interfaces (BCIs)** cost tens of thousands of dollars and stay locked inside research labs.

Even when someone loses hand and limb control, two abilities often remain strong: moving their eyes and holding visual attention. We turn those abilities into independent movement at hobbyist hardware cost, without surgery and without training a per-person deep learning model.

### Why SSVEP is the right science for a 36-hour build
**SSVEP** stands for *steady-state visually evoked potential*. When you stare at a light flickering at a fixed rate, such as `12 Hz` (12 times per second), the visual cortex at the back of your brain produces tiny electrical waves at that exact same frequency (`12 Hz`) and its harmonics (`24 Hz`).

If four arrows on a screen flicker at four different rates, we do not have to "read thoughts." We simply measure which of the four frequencies shows up strongest at the back of the head. And when a person closes their eyes, the brain naturally produces a strong `8 to 13 Hz` **alpha rhythm**, giving us a built-in, hands-free stop gesture.

---

## 2. What we are building (the 5 parts)

Our system is a closed loop of five parts. Each part has one clear owner so nobody steps on anyone else's code.

### Part 1: The Flicker Screen (`interface/`, owned by Prakhar)
A MacBook Air M2 mounted at eye level shows four large high-contrast arrows on a black background. Because the screen refreshes at `60 Hz`, every flicker period must use a whole number of display frames so the frequency never drifts:

| Direction | Cycle length (frames) | On + Off frames | Exact frequency |
| --- | --- | --- | --- |
| `FORWARD` | 9 frames | 5 on + 4 off | `6.67 Hz` (`60 / 9`) |
| `LEFT` | 7 frames | 4 on + 3 off | `8.57 Hz` (`60 / 7`) |
| `RIGHT` | 5 frames | 3 on + 2 off | `12.00 Hz` (`60 / 5`) |
| `BACK` | 4 frames | 2 on + 2 off | `15.00 Hz` (`60 / 4`) |

**Why these exact numbers?** Each divides `60 Hz` cleanly by counting frames (never `time.sleep()`), all four sit in the `6 to 15 Hz` band where SSVEP is strong, and no frequency is `2x` another (so the `2f` harmonic of `6.67 Hz` at `13.33 Hz` will never be confused with `12.00 Hz` or `15.00 Hz`).

Before any arrow flickers, the app shows a photosensitivity warning screen and waits for `SPACE`. Under each arrow, a progress bar fills up during the `1.5 s` dwell so the rider can see the chair locking onto their choice.

### Part 2: The EEG Headset (owned by Keshav)
Wet gold-cup electrodes with conductive gel sit at **O1, O2, and Oz** on the back of the scalp (directly over the visual cortex). One ear clip acts as the electrical reference (zero point), and the other ear clip acts as the bias/ground for noise rejection. Keshav checks skin contact impedance in the OpenBCI GUI, aiming for under `20 kOhm`.

An **OpenBCI Cyton** board samples the electrodes at `250 Hz` across up to 8 channels and streams wirelessly to a USB dongle on your MacBook. (If we use a Ganglion board instead, it streams 4 channels at `200 Hz` over Bluetooth.)

### Part 3: The Signal Decoder (`bci/`, owned by Vani)
Python reads the live EEG stream through BrainFlow. Every `0.25 s`, Vani's decoder grabs the most recent `1.5 s` window of EEG and runs three steps:

1. **Clean the signal:** A Butterworth band-pass filter (`5 to 40 Hz`) removes slow drift and high-frequency muscle noise, and a `60 Hz` notch filter removes building power-line hum.
2. **Score the 4 arrows:** Canonical Correlation Analysis (**CCA**, primary) and Fast Fourier Transform (**FFT**, baseline/fallback) compare the EEG against sine and cosine reference waves at `f` and `2f` for all four frequencies. If the winning margin clears our confidence threshold, the decoder emits an `Intent` (`FWD`, `LEFT`, `RIGHT`, or `BACK`). Otherwise it emits `NONE`.
3. **Watch for closed eyes:** A parallel detector (`bci/alpha.py`) compares `8 to 13 Hz` power against the rider's eyes-open baseline. Closing the eyes spikes alpha power and emits an immediate `StopRequest(ALPHA)` within `1.0 s`.

### Part 4: The Safety State Machine (`control/`, Prakhar designs/tests, Pratosh integrates)
The decoder is never allowed to spin the wheels directly. Your state machine runs at `20 Hz` (every `50 ms`) and enforces **STOP by default** across four states:

- `STOPPED`: Both wheels are `0`. Default at boot, after looking away, after a forward obstacle block (`< 50 cm`), or after any stale/unknown data (`> 0.5 s`).
- `DWELLING`: One arrow is winning above the confidence threshold. Wheels stay `0` while a `1.5 s` timer fills the dwell bar. If the winning arrow changes, drops to `NONE`, or falls below confidence threshold, the timer resets to `STOPPED`.
- `MOVING`: The same arrow won continuously for `1.5 s`. The chair emits capped wheel speeds **only while that same arrow keeps winning** (Decision D1: hold-to-move). Looking away, switching arrows, or encountering a forward obstacle drops back to `STOPPED` (so in-place turns away from the obstacle remain available).
- `E_STOP`: Latched emergency stop triggered by closed eyes (`ALPHA`), an operator key (`OPERATOR`), or a fault (`FAULT`). Wheels stay `0` until a teammate explicitly presses the re-arm key (`R`) once the stop condition clears.

### Part 5: The Drive Platform and ESP32 Safety Bridge (`motors/` and `firmware/`, Pratosh and Keshav)
A plank and chair with front and rear casters mount onto a `36 V` (actual pack: 7S, about 28 V) dual-hub-motor hoverboard flashed with open-source FOC serial firmware. Instead of connecting the laptop straight to the hoverboard, we put an **ESP32 microcontroller** in between:

- `motors/driver.py` sends ASCII speed lines (`C,<seq>,<left>,<right>\n`) over USB serial at `20 Hz` (`115200` baud).
- **200 ms watchdog:** If the laptop crashes or freezes for `200 ms`, the ESP32 zeros both motors on its own (host simulation: 213 to 250 ms; not measured on the chair). If the USB cable is pulled the ESP32 loses power, and the boards' own timeout (about 500 ms) stops the wheels.
- **Local ultrasonic brake:** An HC-SR04 distance sensor wired to the ESP32 stops forward motion in about `50 ms` if anything enters `OBSTACLE_STOP_CM`, even if the laptop still commands forward.
- **Hardware kill switch:** A physical latching mushroom switch wired in the battery line (planned; no record that it is fitted) cuts motor power instantly, regardless of any software or microcontroller bug.

---

## 3. Mode 1 vs. Mode 2 (must-have vs. stretch)

### Mode 1: Manual Arrow Steering (MUST-HAVE)
Nothing else starts until Mode 1 works reliably. To pass **Gate 4 (Saturday 6:00 pm)**, a teammate sitting in the chair must complete all 8 checks live, **three times in a row**:

1. Four arrows flicker at `60 FPS` on the mounted laptop.
2. Rider stares at `FORWARD`: after `~3.0 s` (`1.5 s` EEG window + `1.5 s` dwell), the chair rolls forward at walking pace.
3. Rider stares at `LEFT` or `RIGHT`: chair turns in place after the dwell.
4. Rider looks away from all arrows: chair stops within `~1.0 s`.
5. Rider closes eyes: chair enters `E_STOP` within `~1.0 s` and stays stopped until a teammate re-arms it.
6. Teammate places an obstacle inside the stop distance while rider still stares at `FORWARD`: chair stops on its own.
7. Teammate walking beside the chair presses the physical kill switch: motion cuts instantly.
8. With nobody looking at any arrow, the chair never moves on its own.

**Fallback ladder (decided Saturday 11:00 am if real-head signal is noisy):** Drop from 4 targets to 3 (remove `BACK`), then to 2 (`FORWARD` + `TURN`), or lengthen the EEG window from `1.5 s` to `2.0 s`.

### Mode 2: Autonomous Object Selection (STRETCH ONLY)
We only start Mode 2 at Saturday `7:00 pm` if Mode 1 passed `3/3` runs at `6:00 pm`. A webcam runs YOLO + ByteTrack (`vision/`) and sends up to 4 real objects (person, door, table) over localhost UDP to `interface/`, which draws flickering boxes over the live camera feed. Staring at a box makes the chair center on that object and drive up to it, stopping near it or on ultrasonic trip. Passing `2/3` runs by Sunday `1:00 am` (**Gate 5A**) unlocks the **Best Physical AI Hack** special track.

### Caregiver Alert (OPTIONAL IDLE-HOUR ADD-ON)
If Mode 1 is done and someone has a spare hour, a Photon 2.0 messaging agent texts a caregiver whenever the chair enters `E_STOP`. Never on the critical path.

### Honest non-goals
We are **not** building a medical device, clinical accuracy claims, outdoor driving, cloud backends, user accounts, or anything that needs Wi-Fi during the live demo.

---

## 4. Team roles and your weekend roadmap

### Who owns which folder
| Teammate | Owns | How their work connects to yours |
| --- | --- | --- |
| **Prakhar (you)** | `shared/`, `interface/`, `control/` (design & tests), `docs/`, video, Devpost, live pitch | You define `shared/protocol.py` first so everyone imports the exact same dataclasses. Your `interface/` displays `ControlStatus`, and your `control/` consumes Vani's `Intent`. |
| **Vani** | `bci/`, `tools/`, `vision/` (Mode 2) | Imports `shared/protocol.py`, feeds `Intent` and `StopRequest(ALPHA)` into `control/`, and builds calibration scripts (`tools/smoke.py` was never written). |
| **Pratosh** | `motors/`, `firmware/bridge/`, `control/` hardware integration | Reviews and finishes `control/` overnight Friday, turns your `MotorCommand` into ESP32 serial lines, and writes `bridge.ino`. |
| **Keshav** | EEG prep, hoverboard FOC flash, chassis, casters, kill switch, ultrasonic wiring | Puts electrodes on you, verifies board pins with a multimeter, builds the physical chair, and walks beside the chair holding the kill switch. |

**How we avoid git conflicts:** One branch and git worktree per folder. Nobody runs `git add .` after kickoff. Every merge to `main` gets reviewed by a second AI model family (`/review-diff`) and should keep `python -m pytest -q` passing (`tools/smoke.py` was never written).

### Your schedule (Friday morning to Sunday afternoon)
- **Friday before 6:30 pm (Phase 0 - Prep):** Post the indoor hoverboard venue question on HackPrinceton Discord, confirm Keshav's hardware checklist, pack 2 USB-C to USB-A adapters, verify `~/venvs/hp26` imports, and check in (`4:30 to 6:30 pm`). Dinner is `5:00 to 6:00 pm`; opening ceremony is `6:30 to 8:00 pm`.
- **Friday 8:00 to 10:00 pm (Phase 1 - Kickoff & Skeleton):** Hacking starts at `8:00 pm` sharp (no project code before `8:00 pm`). Create the public GitHub repo (`8:00 to 8:15 pm`), confirm folder ownership (`8:15 to 8:30 pm`), generate `shared/protocol.py` (`8:30 to 9:00 pm`), and build the `control/state_machine.py` STOP-default skeleton (`9:00 to 9:30 pm`) so Gate 1 `smoke.py` passes by `10:00 pm`.
- **Friday 10:00 pm to Saturday 2:00 am (Phase 2 - Interface, First EEG Check, Control Tests):**
  - `10:00 to 11:30 pm`: Build `interface/flicker.py` (`60 FPS` fullscreen for `60 s` with `0` dropped frames + `SPACE` photosensitivity screen).
  - `11:30 pm to 12:00 am`: Sit as the test wearer while Keshav gels O1/O2/Oz (`< 20 kOhm`). Stare at `12 Hz` for `30 s`, then close eyes for `30 s` so Vani confirms a real `12 Hz`/`24 Hz` SSVEP peak and alpha bump.
  - `12:00 to 1:30 am`: Add queue-driven dwell bars + verify flicker rates within `2%` using `240 fps` phone slow-mo video.
  - `1:30 to 2:00 am`: Start full table-driven tests for `control/state_machine.py`, run `/handoff` for Pratosh, then **sleep `2:00 to 6:00 am`**.
- **Saturday 6:00 to 11:00 am (Phase 3 - Calibration):** Record two labeled EEG sessions with Vani, pick final frequencies/window/threshold from `docs/calibration.md` by `9:30 am`, then run screen-only live selection (`>= 80%` target accuracy, `< 4.0 s` selection time) and `5/5` eyes-closed stops with `0` false stops.
- **Saturday 11:00 am to 6:00 pm (Phase 4 - Real Chair Integration):** Build `app.py` with Vani (`11:00 am to 12:00 pm`), attend Technical Storytelling (`1:00 to 2:00 pm`) *only* if you are not needed as the rider for the `1:00 pm` wheels-off test, tune dwell and speed caps with Pratosh (`3:00 to 4:30 pm`), and record `3` consecutive full Mode 1 passes before the `6:00 pm` go/no-go.
- **Saturday 7:00 pm to Sunday 2:00 am (Phase 5 & Phase 6):** Build the `60 FPS` camera flicker overlay if Mode 2 is a go (Phase 5A) or harden Mode 1 (Phase 5B). **Feature freeze at `1:00 am` Sunday.** Film clean multi-angle demo footage from `1:00 to 2:00 am`, then **sleep `2:00 to 5:00 am`**.
- **Sunday 5:00 to 8:00 am (Phase 7 - Ship):** Edit and upload the 2-minute demo video (`5:00 to 6:30 am`), finalize and submit Devpost by **`7:15 am`**, and rehearse the 2-minute live pitch with Vani (`7:15 to 8:00 am`).
- **Sunday 9:30 am to 2:30 pm (Phase 8 - Judging):** Lead every 2-minute live judge visit at our assigned table. Closing ceremony is `2:30 to 4:00 pm`.

---

## 5. Everything we must submit (and when)

### Deadlines
- **Official HackPrinceton hard deadline:** Sunday, Nov 15 at **`8:00 am` EST** (the schedule PDF mentions `8:15 am`, while the onsite packet calls `8:00 am` a hard cutoff).
- **Our locked internal submit time:** Sunday, Nov 15 at **`7:15 am` EST** (Task 7.6). Never wait until `7:55 am` to upload video or submit Devpost.

### Complete Devpost submission checklist (owned by Prakhar, drafted with Vani)
1. **Public GitHub repository link**
   - Must be created **during** hacking hours (Friday Nov 13 after `8:00 pm` to Sunday Nov 15 before `8:00 am`).
   - All project source code must be written during the 36 hours (planning docs and agent rules prepared beforehand are allowed).
   - Tagged `demo-ok-final` on `main` at the `1:00 am` Sunday freeze.
   - Completed `README.md` (written by Vani in Task 6.4): what it does, exact run commands, hardware list, honest limitations, and team roles.
   - **Never commit:** raw EEG recordings (`data/raw/`), `.mp4`/`.mov` videos, `.env` secrets, or `~/venvs/hp26`.
2. **2-minute demo video (unlisted YouTube URL)**
   - Filmed `1:00 to 2:00 am` Sunday while hardware and batteries are fresh; edited `5:00 to 6:30 am` by Prakhar.
   - Must stay at or under `2:00` minutes and clearly show:
     - Wide angle + second angle of a full Mode 1 run (forward + in-place turn).
     - Close-up of the `60 Hz` arrows and the dwell bar filling up before motion starts.
     - Look-away stop (`< 1.0 s`) and eyes-closed `E_STOP` (`< 1.0 s`) with operator re-arm.
     - Ultrasonic obstacle stop while the rider keeps staring at `FORWARD`.
     - Physical mushroom kill switch cutting motion immediately.
     - Mode 2 object approach clip **only** if Gate 5A passed.
3. **Devpost written sections** (drafted by Vani `2:00 to 4:00 am` from `docs/PRD.md`, `docs/calibration.md`, and `PROGRESS.md`; polished by Prakhar `6:30 to 7:00 am`):
   - *Inspiration:* Independence gap for ALS, spinal cord injury, and cerebral palsy patients.
   - *What it does:* Gaze-steered SSVEP wheelchair with eyes-closed alpha braking and 5-layer hardware/software safety.
   - *How we built it:* OpenBCI + BrainFlow, `5 to 40 Hz` filter + `60 Hz` notch + CCA/FFT at `f` and `2f`, `20 Hz` safety state machine, ESP32 `200 ms` watchdog + ultrasonic bridge, FOC hoverboard platform.
   - *Challenges we ran into:* Real occipital impedance through hair, `60 Hz` frame-exact timing on macOS, stopping in `< 1.0 s` despite a `1.5 s` window, hardware pin safety on `36 V` power.
   - *Accomplishments we're proud of:* Real Phase 3 calibration accuracy (`%`), selection latency (`s`), and verified hardware safety stops.
   - *What we learned & What's next:* Calibration-free SSVEP (FBCCA/TRCA), richer target sets, Mode 2 autonomy, and clinical rehab partnerships.
4. **Track selection (strict packet rule)**
   - **Main Track (pick exactly ONE):** `Healthcare`.
   - **Special Tracks:**
     - `Best Hardware Hack` (yes, core build).
     - `Best Physical AI Hack` (**only** if Gate 5A passed `2/3` runs by `1:00 am`; otherwise leave unchecked so we do not demo an unreliable stretch feature to an extra panel).
5. **Team roster and Discord handles**
   - All 4 team members added to the Devpost project (Prakhar, Vani, Pratosh, Keshav).
   - **All 4 teammates' Discord usernames** listed in the submission per the HackPrinceton onsite packet.

---

## 6. How in-person judging works (Sunday 9:30 am to 2:30 pm)

Uploading the video does **not** replace live judging. Every track visits our assigned spot (announced on Discord after `8:00 am`), and **each live demo is strictly capped at 2 minutes**.

### Your 2-minute live pitch flow
- **`0:00 to 0:15` - Problem:** People who cannot use a joystick lose independent mobility, while clinical BCIs stay stuck in labs.
- **`0:15 to 0:30` - Mechanism:** Stare at a flickering arrow; your visual cortex echoes that exact frequency; our EEG decoder reads it with zero hand movement.
- **`0:30 to 1:20` - Live Demo:** Teammate in the seat (or chair on a stand if indoor riding is restricted by the venue). Show `FORWARD` after dwell, `LEFT`/`RIGHT` turn, look-away stop, eyes-closed `E_STOP` + re-arm, ultrasonic obstacle stop, and kill switch.
- **`1:20 to 1:40` - Safety:** Point out STOP-by-default, `1.5 s` dwell, ESP32 `200 ms` watchdog, ultrasonic cutoff, physical battery kill switch, and photosensitivity screening.
- **`1:40 to 2:00` - Results & Next Steps:** Share our real Phase 3 accuracy (`%`) and latency (`s`), plus honest next steps (calibration-free decoding, Mode 2 object approach, clinical testing).

### How our story maps to the 4 HackPrinceton judging criteria
| Criterion | What to emphasize |
| --- | --- |
| **Creativity** | Brain signals from visual cortex flicker + closing your eyes (alpha waves) as the most natural emergency brake. |
| **Utility** | It physically drives and stops live in front of the judge, guarded by independent ESP32 and battery-level stops. |
| **Charity** | Built to restore low-cost, independent movement for people with ALS, spinal cord injury, or cerebral palsy. |
| **Avidity** | Real measured accuracy and latency numbers, honest boundaries (not claiming medical certification), and photosensitivity care. |

### Non-negotiable safety rules at the judging table
- **Never put a judge or spectator in the chair.** Only our calibrated teammate rides.
- **Screen every viewer** for photosensitive epilepsy before pressing `SPACE` (keep the printed warning card on the table).
- **Kill switch in Keshav's hand** beside the chair on every powered run, and **never charge the hoverboard battery (7S, about 28 V) unattended**.
