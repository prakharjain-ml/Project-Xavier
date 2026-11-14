# AGENTS.md

Instructions for every coding agent in this repo: Cursor, Claude Code, Codex, Antigravity and Copilot.
Humans own this file. The full context and the phase plan live in `.cursor/plans/ssvep-chair.plan.md`.

## What we are building, and with what
We are a team of four at HackPrinceton Fall 2026 (Princeton University, hacking from Friday Nov 13 at 8:00 pm
to Sunday Nov 15 at 8:00 am, Healthcare track). We are building a wheelchair that a person who cannot use a
joystick steers with brain signals, using steady-state visually evoked potentials (SSVEP).

Four arrows on the demo laptop's 60 Hz screen (a MacBook Air M2) flicker at different frequencies: FORWARD
6.67 Hz, LEFT 8.57 Hz, RIGHT 12 Hz and BACK 15 Hz, which are 9, 7, 5 and 4 frames per cycle. The rider looks
at one arrow. Wet gel electrodes at O1, O2 and Oz over the visual cortex, with the reference and bias on ear
clips, feed an OpenBCI board (planned as a Cyton: 8 channels at 250 Hz), which streams to the laptop through its
USB dongle. Python reads the stream with BrainFlow, filters it (band-pass and a 60 Hz notch), and scores each
frequency with CCA and FFT over a 1.5 s window every 0.25 s. An alpha-rhythm detector treats closed eyes as a
stop request.

A safety state machine (STOPPED, DWELLING, MOVING, E_STOP) runs at 20 Hz. It moves the chair only after the rider
holds one arrow for a 1.5 s dwell, and only while that arrow keeps winning. Commands go over USB serial to an
ESP32 safety bridge, which runs its own 200 ms watchdog, enforces an ultrasonic obstacle stop, and sends speed
frames to a hoverboard mainboard running open-source FOC firmware. Two hoverboard hub motors on a 36 V
lithium-ion pack move a plank-mounted chair with stabilizing casters. A physical kill switch cuts motor power.

Mode 1 (the must-have demo) is the four arrows. Mode 2 (a stretch goal, only after Mode 1 works) uses a webcam
with YOLO and ByteTrack to put flickering boxes on real objects, and the chair drives to the one the rider picks.

## Read before working
1. `.cursor/plans/ssvep-chair.plan.md`: context, hardware, locked decisions, phases, owners, gates. Work only on
   the current phase, which is named on the team board in `PROGRESS.md`.
2. `docs/INTERFACES.md`: every message and serial format between folders. Never change a contract silently.
3. `docs/SAFETY.md`: the states, transitions and test protocol. These are non-negotiable.
4. `PROGRESS.md`: the live state. Your folder's section is your handoff.

## Hard rules
1. The default motor command is STOP. Any exception, timeout, stale data, low confidence or unknown state
   produces STOP.
2. Never run anything that opens a serial port, uploads firmware, connects to the EEG board, or drives the
   motors. Humans run hardware. Use `MockSerial` and the synthetic board.
3. Edit only the folder named in the prompt. `shared/`, `docs/`, `AGENTS.md` and `.cursor/` change only when the
   human asks.
4. Ask instead of assuming. When a requirement is ambiguous, ask one question before writing code.
5. Make the smallest change that works. No drive-by refactors, renames or reformatting.
6. Plan in 3 to 6 bullets before coding. Explain non-obvious lines in comments, especially signal processing,
   timing and state transitions, because a teammate is learning from this code.
7. Every change ships with evidence: the command you ran and its real output, a passing test, or a saved plot.
   Never write "this should work".
8. Before you stop, update your folder's section of `PROGRESS.md` and propose a commit message.
9. No secrets in the repo, no new dependencies without a stated reason, no new top-level folders.

## Environment
- macOS on Apple Silicon, Python 3.12, virtual environment outside the repo: `source ~/venvs/hp26/bin/activate`
- Tests: `python -m pytest -q`. End-to-end check before any merge: `python tools/smoke.py`
- pygame must run on the main thread on macOS. Flicker is timed by counting frames, never with sleep().
- ESP32 bridge code is an Arduino sketch in `firmware/bridge/`; humans compile and upload it.

## Ownership (locked at kickoff)
| Folder | Owner | Purpose |
| --- | --- | --- |
| `bci/` | Vani | BrainFlow acquisition, filters, FFT and CCA decoder, alpha detector |
| `interface/` | Prakhar | pygame flicker screen, dwell feedback, warning screen, Mode 2 overlay |
| `control/` | Prakhar (design and tests), Pratosh (integration) | Safety state machine, target-to-speed mapping |
| `motors/` | Pratosh | Laptop-side serial driver, mock serial, human-only teleop |
| `firmware/` | Pratosh and Keshav | ESP32 bridge sketch, hoverboard pin map and flashing notes |
| `vision/` | Vani | YOLO and ByteTrack, TargetSet, visual servoing (Mode 2) |
| `shared/` | Prakhar | `protocol.py`, generated from `docs/INTERFACES.md` |
| `tools/` | Vani (primary; coordinate before editing) | Fake EEG, recorder, analysis, smoke test |
| `docs/` | Prakhar | PRD, architecture, interfaces, safety, demo, calibration results |
