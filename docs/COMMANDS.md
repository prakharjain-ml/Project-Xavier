# Demo commands (copy from here)

Open a terminal in the project folder first:

```
cd "/Users/prakharjain/HP Auto WheelChair"
```

## Before you start
- OpenBCI GUI closed (Cmd+Q).
- Laptop on the `OpenBCI-xxxx` Wi-Fi (only for the jaw modes).
- Pixel plugged in, Webcam mode, rear camera, screen on.
- ESP32 plugged in by USB, Arduino Serial Monitor closed (only for the chair modes).

## The commands

Eyes + jaw clench (headset), no motors:
```
./demo.sh jaw
```

Same, reusing the saved eye calibration:
```
./demo.sh jaw --skip-calibration
```

Eyes only, confirm by looking 1.5 s (no headset):
```
./demo.sh dwell
```

Jaw + route + chevrons, FAKE motor port (nothing moves):
```
./demo.sh mock
```

REAL hoverboard, jaw confirm (wheels up first, kill key in hand):
```
./demo.sh chair
```

REAL hoverboard, BLINK TWICE to confirm (SPACE also works; S = emergency stop; wheels up first):
```
./demo.sh chair-blink
```

REAL hoverboard, press SPACE to confirm (no headset needed; S = emergency stop in this mode; wheels up first):
```
./demo.sh chair-key --skip-calibration
```

Same with a FAKE motor port (nothing moves):
```
./demo.sh mock-key --skip-calibration
```

REAL hoverboard, confirm by looking (backup if the headset fails):
```
./demo.sh chair-dwell
```

Mouse preview of the route (no eyes, no headset, no motors):
```
./demo.sh preview
```

## If something is wrong

Calibration shows the room instead of your face (cameras swapped):
```
EYE_CAM=0 ROOM_CAM=1 ./demo.sh jaw
```

Channel 2 electrode keeps failing (use channel 1 only):
```
JAW_CHANNELS=1 ./demo.sh jaw
```

Phone mounted on the chair: give its height (m) and downward tilt (degrees):
```
CAM_HEIGHT=0.9 CAM_PITCH=20 ./demo.sh chair
```

Find the ESP32 port (plug into the ESP32's COM port, not USB):
```
ls /dev/cu.wchusbserial* /dev/cu.usbserial-* /dev/cu.usbmodem*
```

Name the ESP32 port yourself (when several serial devices are plugged in):
```
ESP32_PORT=/dev/cu.wchusbserial1420 ./demo.sh chair-key --skip-calibration
```

Jaw clench not working? Test the headset alone (over the OpenBCI Wi-Fi): double-click `Start jaw-flash.command`.
It closes the OpenBCI GUI, waits until you join the 'OpenBCI-xxxx' Wi-Fi, then shows a black screen that flashes
WHITE for 1 s on each clench. Keep your jaw relaxed for the first 3 s. The first RED line on screen is where it
breaks. UP/DOWN = threshold, R = re-measure rest, ESC = quit.

## After a run
Every run writes a log file to `data/raw/sessions/`. Tell Claude "check the last session" and it can read it:
- A second file, `..._jaw.log`, has only the headset: calibration result, the live level once a second, and
  `JAW CLENCH RECOGNISED #n` for every clench the detector counted.
- `JAW CLENCH detected` = the headset saw a clench.
- `CONFIRMED chair #4 ...` = that clench (or dwell) chose an object.
- `state STOPPED -> DWELLING -> MOVING` = the chair would drive.

## Keys while it runs
| Key | Does |
| --- | --- |
| C | re-centre the gaze (look at the "+" first) |
| X | cancel the destination |
| SPACE | emergency stop (stays stopped). In the -key modes SPACE confirms and S is the emergency stop |
| R | re-arm after SPACE |
| triple blink | while driving to a destination: stop the chair, forget the destination, gaze highlighting comes back |

While driving (after a confirm on a real chair) only the destination stays outlined, gaze does not change the target,
and every wheel command shows in the session log as `MOTOR chair.forward(n)` / `chair.turn_right(n)` / `chair.drive(l, r)` / `chair.stop()`.
| Q | quit (prints the fps and gaze numbers) |
