# firmware/

**Owner:** Pratosh and Keshav

**Purpose:** Everything that runs below the laptop: the ESP32 safety bridge sketch, and the notes and tools for
flashing and wiring the hoverboard mainboards.

| In | Out |
| --- | --- |
| Command lines from `motors/driver.py` over USB serial; ultrasonic echo | 9-byte speed frames to the hoverboard master board over 3.3 V UART (19200 baud); `D,<distance_cm>,<state>` lines back to the laptop |

## Files
| Path | What |
| --- | --- |
| `bridge/bridge.ino` | ESP32-S3 sketch: `C`/`S` line parser, 200 ms watchdog, HC-SR04 read, forward-obstacle stop, clamp to `MAX_SPEED`, hoverboard frame encoder |
| `hoverboard/flash_tools/` | Windows double-click scripts (OpenOCD + ST-Link V2) to unlock, flash and debug the GD32E235 boards, plus prebuilt `.bin` files |
| `hoverboard/firmware_src/` | Our board layout `defines_2-3-9.h` and a patch against RoboDurden's firmware, to rebuild the `.bin` files |
| `hoverboard/tools/bridge_bench_test.py` | HUMAN ONLY wheels-in-the-air test of laptop -> bridge -> hoverboard |

## The hoverboard hardware (verified by Keshav, Nov 14)
- Split hoverboard, two **YK187** mainboards, MCU **GD32E235** (pin compatible with GD32E230, runs the E230 = `TARGET 3` build).
- **No external crystal** on the board: firmware must use the internal clock (`__SYSTEM_CLOCK_72M_PLL_IRC8M_DIV2`).
  RoboDurden's prebuilt Keil binaries hang in `SystemInit()` waiting for the crystal; build with PlatformIO instead.
- Chip reports 32 KB in its flash-size register but has 64 KB; we build with `FLASH_SIZE_OVERRIDE=65536`.
- Battery: 7S Li-ion (27.7 V measured, 29.4 V full), yellow XT60. Firmware `BAT_CELLS=7`.
- Master board = the half with the buzzer.
- Factory firmware was read-protected; it is **erased** on the master (no backup possible).

### Pin map, master board (layout `2-3-9`)
| Function | Pin | Status |
| --- | --- | --- |
| SWD: SWDIO / SWCLK / GND / 3.3V | PA13 (chip pin 34) / PA14 (pin 37) / GND / VDD | VERIFIED: 4 small holes next to the "GND" silkscreen, between the MCU and U9 |
| Hall A / B / C | **PF1 / PA0 / PC15** | VERIFIED: found by turning the wheel by hand (`hall_watch.py`), order chosen by 12 test builds (test03 smoothest) |
| BLDC high side G / B / Y | PA10 / PA9 / PA8 | VERIFIED (normal hi/lo order, like layout 2-3-2) |
| BLDC low side G / B / Y | PB15 / PB14 / PB13 | VERIFIED |
| Battery voltage | PA4 | VERIFIED (reads ~31 V at 28.5 V charger: scale ~9% high, not calibrated yet) |
| DC current sense | PA6 | NOT verified (copied from layouts 2-3-1 / 2-3-2) |
| Phase current A / B | PB0 / PB1 | NOT verified (from 2-3-2) |
| Self-hold (keeps power on) | PB2 | NOT verified (from 2-3-1 / 2-3-2). Until verified: bridge or clamp the power button |
| Power button | - | not used (`DISABLE_BUTTON`) |
| LEDs, buzzer | - | not mapped (PF1 is a hall here, so the 2-3-x LED pins do not apply) |
| ESP32 UART (REMOTE_USART 0) | PB6 = TX (chip pin 42), PB7 = RX (pin 43) | pins from the E230 template; which of the 4 round pads is which must be beep-tested |
| Master-slave cable (USART1) | PA2 / PA3 | from the E230 template, original 4-pin cable |
| **Never connect** | VCC / 15 V pin of any header | to the ESP32 or ST-Link |

The slave board is very likely the same design; confirm its hall pins with `hall_watch.py` before flashing `e235_slave.bin`.

## Hoverboard UART protocol (VERIFIED against the flashed firmware)
This replaces the provisional "ESP32 to hoverboard" section of `docs/INTERFACES.md` (that section assumed the
EFeru FOC firmware: 0xABCD, 115200 baud, 8 bytes). **`docs/INTERFACES.md` still needs updating by its owner.**

- RoboDurden Hoverboard-Firmware-Hack-Gen2.x-GD32, `REMOTE_UART`, `Src/remoteUart.c`
- **19200 baud** 8N1, 3.3 V logic, on the master board's PB6 (TX) / PB7 (RX)
- Command frame, 9 bytes, little-endian, packed: `uint8 '/'`, `int16 speed`, `int16 steer`, `uint8 wStateMaster`,
  `uint8 wStateSlave`, `uint16 crc` with CRC16-CCITT (poly 0x1021, init 0) over the first 7 bytes.
  Example: speed=100, steer=0 -> `2F 64 00 00 00 00 00 A6 BD`
- The board sets speed 0 by itself after **500 ms** without a valid frame (`LOST_CONNECTION_STOP_MILLIS`).
- Feedback frame every 100 ms: `uint16 0xABCD, int16 speedL, int16 speedR (0.01 km/h), uint16 volt (0.01 V),
  int16 ampL, int16 ampR (0.01 A), int32 odomL, int32 odomR (hall steps), uint16 crc` (not forwarded by the bridge yet).
- Units: speed/steer are PWM in -1000..1000 (`DRIVING_MODE 0`). Signs on the real chair: VERIFY wheels-up
  (`SPEED_COEFFICIENT` / `STEER_COEFFICIENT` in the firmware `config.h`).

## Firmware builds (prebuilt in `hoverboard/flash_tools/`)
| File | Board | What it does |
| --- | --- | --- |
| `e235_single_uart.bin` | master, alone | `SINGLE` + `REMOTE_UART`: one board driven by the ESP32. For testing before the slave is done |
| `e235_master.bin` | master | `MASTER` + `REMOTE_UART`: ESP32 commands in, forwards the second wheel's command to the slave over the cable |
| `e235_slave.bin` | slave | `SLAVE`: takes its commands from the master over the cable |
| `motor_tests/test01-12.bin` | any | `REMOTE_DUMMY` slow zigzag, all 6 hall orders x 2 hi/lo orders (test03 = right one for the master) |
| `autodetect_e235_irc.bin` | any | RoboDurden autodetect over RTT (internal clock). Works, but the RTT console was unreliable on charger power |

All use: layout 2-3-9, internal clock, `BAT_CELLS=7`, `DISABLE_BUTTON`, `DISABLE_CHARGESTATE`, `FLASH_SIZE_OVERRIDE=65536`.

### Rebuild from source
```
git clone https://github.com/RoboDurden/Hoverboard-Firmware-Hack-Gen2.x-GD32.git
cd Hoverboard-Firmware-Hack-Gen2.x-GD32
git checkout c63b29a33175d89caa2abbe7a987e3db38b75640
git apply <this repo>/firmware/hoverboard/firmware_src/robodurden-c63b29a.patch
cd HoverBoardGigaDevice
pip install platformio
pio run -e e235_master          # also: e235_slave, e235_single_uart, e235_test, e230_autodetect_rtt
arm-none-eabi-objcopy -O binary .pio/build/e235_master/firmware.elf e235_master.bin
```
The patch adds `Inc/defines/defines_2-3-9.h` and PlatformIO envs, makes `LAYOUT`, `BAT_CELLS`, `MASTER`/`SLAVE`
and `REMOTE_UART` settable from `platformio.ini`, adds `FLASH_SIZE_OVERRIDE`, and lowers autodetect's motor power
(`AD_SAFE_PWM`) so a 2 A charger does not brown out. If the build path has spaces, PlatformIO's final `objdump`
listing step fails after `firmware.elf` is linked; the `.elf` is fine.

## Flashing (Windows, ST-Link V2 clone, humans only)
1. Install the ST-Link driver if Device Manager shows "STM32 STLink" with a warning (Zadig -> WinUSB works).
2. Download **xPack OpenOCD 0.12.0-7** (`xpack-openocd-0.12.0-7-win32-x64.zip`) and unzip it to
   `firmware/hoverboard/tools/xpack-openocd-0.12.0-7/` (git-ignored). Older OpenOCD cannot identify GD32E23x.
3. Wire ST-Link 3.3V, GND, SWDIO, SWCLK to the SWD holes (RST and 5V unconnected). Battery unplugged.
4. Double-click in `firmware/hoverboard/flash_tools/`:
   - `0_test_connection.bat` (read only) -> must end `CONNECTED OK` and show `PROTECTION : LOW` or `OFF`
   - `2_unlock_wipe.bat` (type `YES`, **erases factory firmware**), unplug ST-Link USB 5 s, run `0_...` again -> `PROTECTION : OFF`
   - `7_flash_firmware.bat` -> 1 / 2 / 3
   OpenOCD's built-in `stm32f1x unlock` must NOT be used: OpenOCD does not know this chip revision
   (device id `0x23030410`) and would write a wrong user option byte. `gd32e23x_tools.tcl` follows GigaDevice's SDK.
5. After the 3.3V wire is removed, the board can be powered from the hoverboard charger while flashing.
   **Never connect ST-Link 3.3V and the charger at the same time.**

Other tools: `6_flash_motor_test.bat` (zigzag tests), `8_openocd_server.bat` + `hall_watch.py` (find hall pins),
`5_diagnose.bat` (where is the CPU stuck), `4_autodetect_console.bat` + `rtt_console.py` (autodetect over RTT).

Known issue: with the board on charger power, SWD reads over hand-held jumper wires are glitchy (bytes read as 00,
bit slips). Flashing is fine (verified by CRC on the chip), but the RTT console is not trustworthy. Solder a header
for long debug sessions.

## ESP32 bridge
- Arduino IDE 2 + "esp32 by Espressif Systems" board package; board **ESP32S3 Dev Module**.
- If you plug into the S3's native USB port, set **Tools -> USB CDC On Boot -> Enabled** so `Serial` is the USB port.
- Wiring: GPIO17 -> board PB7, GPIO18 <- board PB6, GND - GND. HC-SR04: TRIG GPIO4, ECHO GPIO5 through a
  1k/2k divider (ECHO is 5 V), VCC 5 V, GND.
- Laptop protocol: `docs/INTERFACES.md` ("Laptop to ESP32 bridge"). Bench test: `python firmware/hoverboard/tools/bridge_bench_test.py <port>`.

## Done when
Unplugging the laptop stops the wheels within 200 ms, a hand in front of the ultrasonic sensor stops forward motion,
and the pin map is written here before anything is connected.

Humans compile and upload. Agents only write and review the sketch. Rules: `.cursor/rules/50-motors.mdc`, `AGENTS.md`. Contracts: `docs/INTERFACES.md`.
