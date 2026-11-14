# Hoverboard bring-up: debug log (Nov 14, 2026)

Everything we tried to get the master board (YK187, GD32E235) talking to the ESP32-S3, in order: what we did, what
happened, and what it taught us. Owner: Keshav (hardware), with Claude Code.

## TL;DR (current state)
- Firmware **`e235_single_usart1.bin` (option 1) runs correctly** on the master. Verified with the debugger:
  72 MHz clock (IRC8M/2 x 18), USART1 enabled, BAUD register = 19200, PA2 actively transmitting feedback frames.
- **The ESP32 link is the master's 5-pin plug** (the white cable to the other board), NOT the 4-pin plug and NOT the
  round "group B" pads:

  | 5-pin plug pin | Measured | Wired to |
  | --- | --- | --- |
  | P1 | 0 V | GND through something (NOT a solid ground, see below) |
  | **P2** | 3.3 V idle | **PA2 = board TX** (verified both directions) |
  | **P3** | 3.3 V idle | **PA3 = board RX** (verified both directions) |
  | P4 | 0 V | not a chip signal (shorting it changes nothing) |
  | **P5** | **~14 V** | **power: never connect to the ESP32** |

- **Root cause of all the "noise / NOT FOUND" results: no solid ground between ESP32 and board.** The ESP32 GND was on
  5-pin P1; the edge capture showed a 60 Hz mains-hum square wave instead of data. Fix in progress: ESP32 GND to the
  thick black battery wire or the SWD "GND" hole.
- Final wiring to try: ESP32 GND -> solid board GND, GPIO17 -> P2, GPIO18 -> P3 (any order, `bridge.ino` auto-detects
  TX/RX), nothing on P1/P4/P5. Then `python bridge_bench_test.py COM4 120`.

## Timeline

### 1. Unlock + flash (worked)
- OpenOCD 0.11 could not identify the chip -> xPack OpenOCD 0.12.0-7 (device id 0x23030410).
- OpenOCD's `stm32f1x unlock` misdecodes this chip revision -> custom `gd32_unlock` (GD SDK style option byte write).
  ST-Link reports a write error but the write succeeds; power cycle applies it. Protection now OFF.
- Prebuilt Keil binaries hang in `SystemInit` (no crystal on the board) -> PlatformIO build with
  `__SYSTEM_CLOCK_72M_PLL_IRC8M_DIV2`. Flash-size register says 32 KB, real 64 KB -> `FLASH_SIZE_OVERRIDE=65536`.

### 2. Pin mapping (worked)
- RoboDurden autodetect over RTT was unreliable (glitchy hand-held SWD wires on charger power) -> abandoned.
- Halls found by turning the wheel and reading GPIO via the debugger (`hall_watch.py`): PF1 / PA0 / PC15.
- Hall order found by flashing 12 test builds: **test03 smoothest**. Motor spins with our firmware.

### 3. Round "group B" pads (GND / ? / TX / RX) - dead end
- Beep test: pads do not connect to chip pins 42/43 (PB6/PB7), also no reading on 2k/20k ohm.
- With option 4 (`e235_single_uart`, USART0 = PB6/PB7) flashed, all pads still read 0 V (a live TX idles at 3.3 V).
- Debugger drove PB6 high: no pad followed.
- Conclusion: pads are not connected (series resistors R10/R11 most likely not fitted). Usable only with soldering.

### 4. 4-pin plug - dead end
- Assumed (from the E230 template) to be USART1 PA2/PA3. Beep test: no pin beeps to chip pins 12/13.
- Voltages: P1 1.18 V, P2 1.18 V, P3 0 V, P4 3.3 V. No pin above 3.6 V.
- ESP32 probe sketches: only "noise", never a valid frame, on any pin.
- Debugger blink of PA2 (1 Hz) with a multimeter: no 4-pin pin follows. Not the UART.

### 5. Was the firmware even running? (yes)
- Read registers live over SWD (`diag_uart.py`): CPU running (PC changes), PLL on, SysTick 1 ms, USART1 CTL0 = 0x0D
  (UEN/REN/TEN), BAUD = 0xEA6 (72 MHz / 3750 = 19200), PA2/PA3 in AF1, PA2 low in 153/1930 samples = transmitting.

### 6. 5-pin plug - the right connector
- Voltages: P1 0, P2 3.3, P3 3.3, P4 0, P5 ~14 V.
- **Pin watch** (`pinwatch.py`, chip halted, read GPIO inputs while shorting plug pins to P1): P2 -> PA2 LOW,
  P3 -> PA3 LOW (each twice), P4 -> nothing.
- **Blink check**: debugger toggled PA2 / PA3 at 1 Hz -> multimeter on P2 / P3 jumped 0 <-> 3.3 V. Path works both ways.

### 7. ESP32 still could not decode the data -> it was the ground
- `hover_probe` (19200, CRC-checked frames): ~70-85 bytes per 0.5 s on P2, never a valid frame.
- `hover_scan` (9600-60000 baud, normal + inverted): garbage at every rate.
- `hover_edges` (timestamps every edge on GPIO18): ~8 ms high / 8 ms low (60 Hz) with hundreds of 2-5 us flickers at
  each transition, no 52/104 us UART bit pulses. That is mains hum between two un-grounded devices (laptop USB vs
  hoverboard charger), i.e. **P1 is not a usable ground**.
- Side lesson: Arduino IDE kept stale copies of sketches that changed on disk, so some uploads were old versions.
  Always File -> Open fresh (or use a new sketch folder).

## Tools written (local, `flash_tools/` and sketch folders)
| Tool | Purpose |
| --- | --- |
| `bridge/bridge.ino` + `hover_link.h` | Real bridge. Now **auto-detects TX/RX** per board (listens for valid feedback frames before sending), prints `# LEFT board OK/NOT FOUND` when the laptop starts talking |
| `hover_probe/`, `hover_scan/`, `hover_edges/` | ESP32 diagnostics: frame sniff at 19200, baud/polarity sweep, raw edge timing |
| `diag_uart.py`, `pinwatch.py`, `blink.py`, `pintoggle.py` | OpenOCD Tcl (port 6666) helpers: read clocks/UART regs live, watch which GPIO a plug pin drives, blink a pin for a multimeter |
| `bridge_bench_test.py COM4 [speed]` | Wheels-up drive test, prints the bridge's board-found messages |
| `e235_usart1_9600/4800/2400.bin` | Option 1 at slower baud (built in case of a filtered line; probably not needed now that the ground is the cause) |

## Lessons
1. **Common ground first.** Use the thick black wire or the SWD GND hole, never a plug pin that only reads 0 V on a meter.
2. A multimeter's 0 V says nothing about how solid a ground is; a pin watch pull-down works even through a resistor.
3. Do not trust a vendor template's connector mapping; prove it with the debugger (pin watch + blink).
4. Separate "is the firmware running" from "is the wire right": reading peripheral registers live over SWD answered
   the first question in 10 seconds.

## Still to do
- [ ] ESP32 GND on a solid ground -> `bridge_bench_test.py` shows `LEFT board OK`, wheel moves; set `LEFT_SIGN`.
- [ ] Slave: unlock, test03, option 1, find its 5-pin P2/P3 the same way, wire GPIO15/16.
- [ ] Update `firmware/README.md` pin map (5-pin plug, not 4-pin) and push the auto-detect `bridge.ino`.
- [ ] `docs/INTERFACES.md`: laptop parsers must ignore lines starting with `#`.
