# MOTOR_COMMANDS: what we actually tell the hoverboard, and why

Written Sat Nov 14, ~7:15 pm, from the code on branch `prakhar/gaze` (commit `2b3a6cf`). Every claim names the file
it comes from. Lines marked **UNVERIFIED** have never been measured on the real chair.

## 1. The short answer

We send **one thing only: a target power level for each wheel, 20 times a second.**

| Question | Answer |
| --- | --- |
| Do we tell it an angle ("turn 30 degrees")? | **No.** No message carries an angle. |
| Do we tell it a time ("drive forward for 2 s")? | **No.** No message carries a duration. |
| Do we tell it a distance ("go 1.5 m")? | **No.** |
| Do we tell it an acceleration? | **No.** The laptop limits how fast the number may grow, but the number sent is still a power level. |
| Do we tell it a speed? | **Roughly.** We send a signed number per wheel, `left` and `right`, each from -150 to +150. The hoverboard treats it as motor power (PWM duty on a -1000 to +1000 scale), so 150 means 15% power. It is not metres per second. |
| Do we ever "use the left wheel only"? | Not as a special command. A turn is simply two different numbers: the outer wheel gets the larger one. |

A movement lasts only as long as we keep sending it. Each line means "do this for the next 50 ms". The chair turns
30 degrees because the camera keeps saying "the target is still off to the left", and it stops turning when the
camera says the target is centred. The camera closes the loop, not a counter and not a clock.

### Why power levels, repeated, and not "turn 30 degrees" or "drive 2 s"
1. **Safety.** A command like "drive 2 s" keeps running if the laptop crashes halfway. A command that must be
   repeated every 50 ms dies by itself: no new line, no motion. That is hard rule 1 in `AGENTS.md` (the default is
   STOP), and it is why several separate timeouts exist (section 6).
2. **The chair cannot measure an angle or a distance.** No wheel encoder reading reaches the laptop, and there is no
   compass or gyro. "Turn 30 degrees" would be a guess from time and power, and the guess changes with the rider's
   weight, the floor and the battery level.
3. **The camera can measure what we care about.** On every frame it gives the target's direction and distance
   again. Steering from that fresh reading corrects for slip, weight and battery without knowing any of them.
4. **The rider must be able to stop instantly.** Look away, and the very next line is a stop. A queued
   "drive 2 s" could not be cancelled that cleanly.
5. **It keeps the firmware simple.** The hoverboard firmware already accepts a power level. Anything smarter would
   mean writing and flashing motor-control code we cannot test in a weekend.

## 2. The chain, end to end

```
camera + gaze            planner               safety state machine       laptop driver             ESP32 bridge              hoverboard boards
vision/object_select -> control/goto.py     -> control/state_machine.py -> motors/driver.py      -> firmware/bridge/       -> RoboDurden firmware
"target is 2 m ahead,    control/navigation    "may the chair move        soft start, then one      bridge.ino                one board per wheel
 10 deg to the right"    "0.4 m/s, turn        at all?"                   text line every 50 ms     watchdog, obstacle        turns the number into
                          -12 deg/s"           (left, right) or STOP      over USB                  stop, 9-byte frames       motor power
```

Each stage can only make the command **smaller or zero**. No stage can add speed that an earlier stage refused.

## 3. Step by step

### 3.1 The planner decides a speed and a turn rate (`control/navigation.py`, `control/goto.py`)
- Input, every camera frame: where the confirmed object is (its position in the picture gives a direction; the
  height of its box gives a distance), every other object the camera sees, and the ultrasonic distance.
- Method: the Dynamic Window Approach. It tries many pairs of (forward speed, turn rate) that the chair could reach
  in one step, imagines each one for 1.5 s, throws away any that pass within 0.45 m of an obstacle, and picks the
  one that points best at the target while keeping speed.
- Output: forward speed `v` in m/s and turn rate `w` in rad/s. Not an angle, not a duration.
- Limits (`NavConfig`): top speed 0.4 m/s (a slow walk), top turn rate 40 deg/s, speed may change by 0.3 m/s per
  second, never reverses (the rider cannot see behind).
- Why a turn *rate* and not a turn *angle*: the planner runs again on the next frame with a new measurement. It
  never needs to know how far it has turned, only which way to turn now.
- When it stops: the target reads closer than 0.7 m, or the camera can no longer measure it getting closer (its box
  fills the picture, or its base has left the bottom of the picture). Then the answer is (0, 0) and "arrived".
- No distance estimate, or a reading that cannot be trusted: (0, 0). It does not guess.

### 3.2 Speed and turn rate become two wheel numbers (`to_wheels` in `control/navigation.py`)
- Differential drive: `left = v - w * half_track`, `right = v + w * half_track`, with 0.55 m between the wheels
  (**UNVERIFIED**, measure on the chair). The outer wheel of a turn gets the larger number.
- Scaling: the fastest wheel the planner can ever ask for (0.592 m/s) maps to 150. So:
  - straight at top speed (0.4 m/s) is about **(101, 101)**
  - fastest turn on the spot (40 deg/s) is about **(-50, +50)** to the left
- Dead band: the hoverboard firmware ignores anything under 50 (**UNVERIFIED**, the number comes from a comment in
  `bridge.ino`). So every wheel number comes out as 0 or at least 50. Why: before this fix a slow turn came out as
  (-49, 49), the board ignored it, and the chair stood still while the planner believed it was turning.
- The conversion from m/s to these units is an assumption, not a measurement. Nobody has timed the chair over a
  known distance. The numbers are power, so the real speed changes with load and battery.

### 3.3 Arrow mode uses fixed numbers instead (`provisional_mapping` in `control/state_machine.py`)
Used by `app.py --gaze` and `app.py --keyboard`. No planner, just a table:

| Arrow | left | right | Why |
| --- | --- | --- | --- |
| FORWARD | 150 | 150 | the cap |
| BACK | -75 | -75 | half speed, the rider cannot see behind |
| LEFT | -120 | 120 | turn on the spot: wheels run opposite ways |
| RIGHT | 120 | -120 | same, mirrored |

The turn continues for exactly as long as the rider keeps looking at the arrow.

### 3.4 The safety state machine decides whether anything moves (`control/state_machine.py`)
- Runs 20 times a second. States: STOPPED, DWELLING, MOVING, E_STOP.
- It passes the wheel numbers on **only** in MOVING, which needs the rider to have held the same target for 1.5 s
  and to still be holding it. In every other state the command is STOP.
- STOP also on: no input for 0.5 s (this is what stops the chair on a frozen camera), a forward command with
  something closer than 50 cm, the operator's SPACE key (latched until R), or any error inside the function.
- It clamps both numbers to +-150 again.

### 3.5 The laptop driver sends one text line every 50 ms (`motors/driver.py`, `motors/bridge_protocol.py`)
USB serial, 115200 baud, plain text so a human can read it in a serial monitor:

```
C,<seq>,<left>,<right>\n     drive, e.g.  C,412,101,101
S,<seq>\n                    stop,  e.g.  S,413
```

- `seq` is a line counter. The ESP32 parses it and does nothing with it; it is there for reading logs.
- A line goes out every 50 ms **even when stopped**. Why: silence then means "the laptop is gone", and the ESP32
  can tell that apart from "the laptop says stop".
- Two zero speeds are sent as an explicit `S` line.
- **Soft start:** a wheel's number may grow by at most 8 per line. From standstill to 150 takes 19 lines, about
  0.95 s. Slowing down and stopping are never delayed. A reversal passes through zero. After any stop, a stale
  command or a reconnect the ramp starts again from zero. Why: without it the first line after a 1.5 s hold was a
  jump straight to the cap, which jerks a seated rider.
  - This is the only place "acceleration" exists. It is a limit on the laptop, not something we send.
  - Known gap: the first ramp lines (8 to 48) are inside the dead band, so the wheels should start moving around
    line 7. **UNVERIFIED** on hardware.
- If the control loop gives no new command for 0.2 s, the driver sends STOP by itself.
- It clamps to +-150 a third time.
- It never picks a port by itself and refuses a port whose name looks like the OpenBCI dongle, so a motor line
  can never be written to the EEG board.

### 3.6 The ESP32 bridge checks again and talks to the boards (`firmware/bridge/bridge.ino`)
Every 50 ms it:
1. Reads the newest line. A line it cannot parse, or one that is too long, sets both wheels to zero at once.
2. Fires the ultrasonic sensor (HC-SR04: TRIG on GPIO4, ECHO on GPIO5 through a voltage divider) and converts the
   echo time to centimetres. No echo within 20 ms is reported as `-1` (nothing in range), never as 0.
3. Applies its own rules, which do not depend on the laptop:
   - **Watchdog:** no valid line for 200 ms means both wheels zero, state `WATCHDOG`. It also starts in this state
     at power-up, so nothing moves until the laptop speaks.
   - **Obstacle:** something closer than 50 cm **and** `left + right > 0` (net forward) means both wheels zero,
     state `OBSTACLE`. Turning on the spot and reversing stay allowed, so the rider is never trapped facing a wall.
   - Clamps to +-150 a fourth time.
4. Sends one 9-byte frame to **each** hoverboard board (one board per wheel, each on its own UART, 19200 baud):

   ```
   '/'  speed(int16)  steer(int16)  stateMaster(0)  stateSlave(0)  CRC16
   example: speed 100, steer 0  ->  2F 64 00 00 00 00 00 A6 BD
   ```

   `speed` is that wheel's number times `LEFT_SIGN` or `RIGHT_SIGN` (the two motors are mounted as mirror images,
   so one of them needs -1). `steer` is always 0 because each board drives one wheel. The CRC lets the board throw
   away a frame damaged by electrical noise.
5. Reports back to the laptop: `D,<distance_cm>,<state>\n`, state = `OK`, `OBSTACLE` or `WATCHDOG`. The laptop
   feeds that distance to the planner and to the state machine.

### 3.7 The hoverboard boards turn the number into motor power (RoboDurden Gen2.x firmware, see `firmware/README.md`)
- The number is PWM duty on a -1000 to +1000 scale (`DRIVING_MODE 0`). 150 is 15% power. The firmware does the
  three-phase motor switching using the wheel's hall sensors.
- The board sets itself to zero after 500 ms without a valid frame.
- The board does send a feedback frame (wheel speed, battery voltage), but `bridge.ino` does not read it. So the
  laptop never learns how fast the wheels really turn.

## 4. A worked example: the rider picks a chair 2 m away, 15 degrees to the right

| Time | What happens | Line on the wire |
| --- | --- | --- |
| 0.0 s | Rider looks at the chair and confirms. State goes STOPPED to DWELLING. | `S,...` |
| 0.0 to 1.5 s | Rider keeps looking. The planner already proposes wheel numbers; the state machine withholds them. | `S,...` (30 lines) |
| 1.5 s | State goes to MOVING. Planner wants a right curve. Soft start begins. | `C,...,8,8`, then `16,16`, ... |
| ~1.8 s | Numbers pass 50, wheels start to turn (**UNVERIFIED**). Left wheel gets the larger number, so the chair curves right. | e.g. `C,...,64,50` |
| ~2 to 6 s | Each frame the camera re-measures. As the chair points at the target, the two numbers become equal. | e.g. `C,...,101,101` |
| any time | Rider looks away. | `S,...` on the next line |
| end | Target's base leaves the bottom of the picture, or reads under 0.7 m: "arrived". | `S,...` |

The wire lines in this table are illustrative, not captured from a run. Nobody computed "turn 15 degrees". The
chair turns until the camera says the target is ahead.

## 5. Every number in one place

| Constant | Value | Where | Meaning |
| --- | --- | --- | --- |
| `CONTROL_HZ` | 20 | `shared/protocol.py` | lines per second |
| `MAX_SPEED` | 150 | `shared/protocol.py`, `bridge.ino` | cap on each wheel number (15% power) |
| `TURN_SPEED` | 120 | `shared/protocol.py` | arrow-mode turn |
| `WHEEL_DEAD_BAND` | 50 | `control/navigation.py` | board ignores smaller numbers (**UNVERIFIED**) |
| `SLEW_STEP` | 8 per line | `motors/driver.py` | soft start |
| `DWELL_S` | 1.5 s | `shared/protocol.py` | hold before moving |
| `ARRIVE_M` | 0.7 m | `control/navigation.py` | planner's stop distance |
| `OBSTACLE_STOP_CM` | 50 | `shared/protocol.py`, `bridge.ino` | forward obstacle stop |
| planner top speed / turn | 0.4 m/s, 40 deg/s | `NavConfig` | **UNVERIFIED** against the real chair |
| track width | 0.55 m | `NavConfig` | **UNVERIFIED** |

## 6. The layers that stop the chair when something breaks

| Failure | Who catches it | After |
| --- | --- | --- |
| Camera freezes, gaze lost, rider looks away | state machine (stale or missing intent) | at most 0.5 s |
| Control loop hangs | laptop driver sends STOP | 0.2 s |
| Laptop crashes or USB is pulled | ESP32 watchdog | 0.2 s |
| ESP32 dies or its wire to a board breaks | the hoverboard board itself | 0.5 s |
| All of the above fail | the human on the battery kill switch | - |

## 7. What is not true yet (say this to judges if asked)
- The pushed `bridge.ino` may not be the sketch on the ESP32. Keshav's handoff mentions a newer one with
  `hover_link.h` and `#` info lines, and it is on no GitHub branch as of 7:15 pm. Section 3.6 describes the pushed file.
- `firmware/README.md` says 4-pin plug, the debug log says 5-pin. The wiring section here follows `bridge.ino`.
- `LEFT_SIGN` and `RIGHT_SIGN` are both 1 in the pushed sketch. One of them normally has to be -1.
- No wheel-speed feedback reaches the laptop. The planner assumes the chair does what it was told.
- The m/s figures, the dead band of 50, the track width and the soft-start feel have never been measured on the chair.
- The planner assumes one step is 0.1 s, but it runs once per camera frame, so its internal speed limits are
  approximate. The 150 cap and the soft start hold regardless.
- The blue route drawn on screen is a preview. The wheels follow the planner in section 3.1, not that line.
