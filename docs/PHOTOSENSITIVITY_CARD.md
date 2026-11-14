# PHOTOSENSITIVITY & SAFETY NOTICE (Print or Keep Open at Table)

## Flashing-Light Warning (3 to 30 Hz)
This wheelchair prototype uses flickering visual arrows (`6.67 Hz`, `8.57 Hz`, `12.0 Hz`, and `15.0 Hz`) on a `60 Hz` display to evoke visual-cortex brain signals (SSVEP).

**Before pressing `SPACE` to start the display, ask every viewer within sight of the screen:**
> "Do you or anyone with you have photosensitive epilepsy or a history of seizures or discomfort triggered by flashing lights?"

- If anyone answers **yes** or is unsure, **do not start the flicker** (`ESC` exits immediately).
- Flicker remains off on the start screen until the operator explicitly presses `SPACE`.

## Live Demo Safety Rules
1. **Teammate rider only:** Judges and spectators observe; nobody outside our trained team sits in the chair.
2. **Physical kill switch in hand:** A spotter stands beside the chair holding the `36 V` battery kill switch on every powered run.
3. **Default command is STOP (`0, 0`):** Looking away stops within `~1.0 s`; closing eyes latches `E_STOP`; the ESP32 enforces an independent `200 ms` serial watchdog and `< 50 cm` ultrasonic forward stop.
