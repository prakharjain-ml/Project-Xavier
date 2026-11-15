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

Find the ESP32 port:
```
ls /dev/cu.usbmodem*
```

## After a run
Every run writes a log file to `data/raw/sessions/`. Tell Claude "check the last session" and it can read it:
- `JAW CLENCH detected` = the headset saw a clench.
- `CONFIRMED chair #4 ...` = that clench (or dwell) chose an object.
- `state STOPPED -> DWELLING -> MOVING` = the chair would drive.

## Keys while it runs
| Key | Does |
| --- | --- |
| C | re-centre the gaze (look at the "+" first) |
| X | cancel the destination |
| SPACE | emergency stop (stays stopped) |
| R | re-arm after SPACE |
| Q | quit (prints the fps and gaze numbers) |
