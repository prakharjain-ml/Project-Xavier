# Glossary

Short definitions for this project. All names match `docs/INTERFACES.md` and `docs/SAFETY.md`.

**SSVEP.** Steady-state visually evoked potential. Stare at a light flickering at a fixed rate `f` and the visual cortex produces electrical activity at `f` and its harmonics (`2f`).

**EEG.** Electroencephalography. Microvolt scalp signals sampled at `250 Hz` on OpenBCI Cyton (`200 Hz` on Ganglion).

**O1, O2, Oz.** Standard occipital electrode positions at the back of the head over the visual cortex (`O1` left, `O2` right, `Oz` midline).

**Reference and bias.** Ear-clip electrodes. Reference (`SRB2` on Cyton) is the zero point every EEG channel is measured against; bias/ground on the other ear rejects common-mode mains noise.

**Impedance.** Skin-electrode contact resistance. Lower is cleaner; we aim for `< 20 kOhm` in OpenBCI GUI (close OpenBCI GUI completely before running Python so `/dev/cu.usbserial-*` is free).

**Alpha rhythm.** Natural `8 to 13 Hz` occipital wave that spikes when eyes close (`bci/alpha.py` emits `StopRequest(ALPHA)`).

**FFT.** Fast Fourier Transform. Measures spectral power at `f` and `2f` (baseline/fallback scorer; normalize against neighboring background bins so `1/f` low-frequency slope does not bias `6.67 Hz`).

**CCA.** Canonical Correlation Analysis. Default scorer (Decision D7); measures maximum correlation between multi-channel EEG and `sin`/`cos` reference waves at `f` and `2f`.

**Frame-counted flicker.** Toggling arrow brightness by display refresh count on a `60 Hz` panel (`9 = 5+4`, `7 = 4+3`, `5 = 3+2`, `4 = 2+2` frames) with `vsync=1`, never `time.sleep()`.

**Dwell (`DWELL_S = 1.5 s`).** Continuous time one arrow must keep winning before `DWELLING` transitions to `MOVING`.

**Hold-to-move (Decision D1).** After dwell completes, the chair keeps moving only while that same arrow stays above `CONF_THRESHOLD`. Any target change, `NONE`, low confidence, or stale data (`> 0.5 s`) drops immediately to `STOPPED`.

**`Intent`.** Frozen dataclass from `bci/decoder.py` (`target`, `confidence`, `scores`, `t`).

**`NONE`.** `Target.NONE` - normal output when no arrow clears `CONF_THRESHOLD` (rest, looking away, or noise).

**`E_STOP`.** Latched zero-speed state entered on `StopRequest` (`ALPHA`, `OPERATOR`, or `FAULT`). Stays stopped until an operator presses re-arm with no active `StopRequest`. Forward obstacle (`< OBSTACLE_STOP_CM`) enters non-latching `STOPPED` so the rider can still dwell on a turn away from the obstacle.

**ESP32 bridge.** Microcontroller between the laptop (`C,<seq>,<left>,<right>\n` at `20 Hz`) and the hoverboard FOC UART (`8-byte` frames at `3.3 V`). Enforces its own `200 ms` watchdog and local ultrasonic forward stop (`distance_cm = -1` on echo timeout).

**FOC firmware.** Open-source `EFeru/hoverboard-firmware-hack-FOC` flashed onto the hoverboard mainboard via ST-Link V2.
