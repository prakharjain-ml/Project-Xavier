# Questions for Friday 8:15 pm Kickoff

Read `SAFETY.md` and `INTERFACES.md` before adding to this list. The kickoff walkthrough is 15 minutes (`8:15 to 8:30 pm`). Bring questions that change a constant, wire protocol, or state transition.

Each item below already has a kickoff default written into `INTERFACES.md` and `SAFETY.md` so Phase 1 can run immediately. Confirm or adjust at `8:15 pm` and log any change in `PROGRESS.md`.

## Kickoff defaults to confirm

1. **Look-away `< 1 s` vs. the `1.5 s` window.** Confidence in `bci/decoder.py` combines target-to-runner-up margin with absolute correlation / local SNR so that when the rider looks away, `Intent.target` drops to `NONE` within `< 1 s` instead of waiting a full `1.5 s` for old samples to scroll out.

2. **Obstacle blocks forward (`STOPPED`) without latching `E_STOP`.** When valid ultrasonic distance (`> 0`) is below `OBSTACLE_STOP_CM` (`50 cm`), forward motion (`(left + right) > 0`) is forced to zero on both the ESP32 and laptop (`STOPPED`), while in-place turns (`(-TURN_SPEED, +TURN_SPEED)`) and reverse remain allowed after a fresh dwell so the rider is never deadlocked in front of a wall. Eyes-closed (`ALPHA`), operator key (`OPERATOR`), and faults (`FAULT`) latch `E_STOP`.

3. **Operator re-arm key (`R`) and emergency key (`X`).** Teammate presses `R` to clear `E_STOP` once no `StopRequest` is active; teammate presses `X` to force `E_STOP`.

4. **Kickoff speed constants (firmware units out of `+-1000`).** `MAX_SPEED = 150`, `TURN_SPEED = 120`, reverse = `-MAX_SPEED // 2` (`-75`), `CONF_THRESHOLD = 0.15`, `OBSTACLE_STOP_CM = 50`. Phase 3 replaces `CONF_THRESHOLD` from calibration; Phase 4 tunes speeds on the bench and floor.

5. **Wheel polarity.** Positive `left` and positive `right` mean "roll the chair forward" only after Pratosh and Keshav verify direction with wheels off the ground in Task `2.13`. Flip polarity in one place (`bridge.ino` or `motors/`) if needed and record it in `PROGRESS.md`.

6. **Laptop-to-ESP32 ASCII line protocol (`115200` baud, `20 Hz`).** Laptop sends `C,<seq>,<left>,<right>\n` or `S,<seq>\n`; ESP32 replies `D,<distance_cm>,<state>\n` (`distance_cm = -1` on echo timeout, never `0`). Binary 8-byte FOC frames (`0xABCD`, `steer`, `speed`, XOR checksum) stay strictly between ESP32 and hoverboard UART (`3.3 V`).

7. **Editable root package in Task 1.1 / 1.3.** Add a minimal `pyproject.toml` (`pip install -e .` into `~/venvs/hp26`) and `__init__.py` files at kickoff so `python tools/smoke.py` imports `shared`, `control`, `bci`, and `motors` without `PYTHONPATH` hacks.

## Add yours below

Write the question, the doc it came from, and what must be decided by `8:30 pm`.
