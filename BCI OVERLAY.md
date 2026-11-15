# BCI OVERLAY: replace SPACE / blink confirmation with Vani's BCI clench classifier

Instructions for Vani's coding agent. Read `AGENTS.md` and `docs/SAFETY.md` first. Prakhar asked for this handoff
on Sun Nov 15 after the first full live drive (gaze -> confirm -> A* route -> wheels) worked with SPACE as the
confirm. Goal: **the ONLY way to confirm a destination is a jaw clench recognised by Vani's BCI model.** Keyboard
confirm (SPACE / J), double-blink confirm, triple-blink cancel and dwell confirm are all removed.

Branch: `prakhar/gaze`. Everything below refers to that branch.

---

## 1. What exists today (do not rebuild it)

| Piece | Where | What it does |
| --- | --- | --- |
| Live drive loop | `vision/object_select.py` `run()` | gaze -> highlighted object -> confirm -> `drive_tick()` (A* route, wheels at once, no dwell) |
| Confirm decision | `vision/object_select.py` `confirm_event(mode, key, jaw)` | returns True when this pass confirms |
| Current headset confirm | `bci/jaw_live.py` `JawConfirmSource` | threshold-based EMG clench detector (calibrate, then a reader thread queues one event per clench) |
| Web app session | `interface/web/session.py` `real_jaw()`, `_jaw_fired()` | same `JawConfirmSource` interface, used by the browser flow |
| Vani's model | `models/train.py` -> `clench_model.joblib`; `models/api.py` FastAPI `/predict` | random forest on `ch1_*` / `ch2_*` window features -> CLENCH / RELAX + `clench_probability` |
| Board connection | `bci/jaw_live.py` `connect_board("wifi" or "dongle", port, channels)` | BrainFlow Cyton over the Wi-Fi shield (192.168.4.1:6677) or the USB dongle |

Live findings you need (Sun Nov 15, `data/raw/sessions/`, OpenBCI GUI recordings in
`~/Documents/OpenBCI_GUI/Recordings/OpenBCISession_2026-11-15_05-15-08/`):
- The board streams fine (1000 Hz over Wi-Fi, about 0.3 % of samples lost).
- Channels 1 and 2 move together (level correlation 0.97) with a regular ~4.5 s rhythm up to ~190 uV (most likely
  breathing / lead movement through the ear clips). A HARD clench reaches 700-900 uV; a normal clench sits inside
  the rhythm. The threshold detector therefore refused calibration twice (clench only 1.8x rest, needs 3x).
- Judge your classifier on exactly this kind of data: hold out whole trials, and report false CLENCH windows during
  relaxed breathing, not only accuracy.

## 2. The integration contract (implement exactly this)

Create **`bci/rf_confirm.py`** with a class **`RandomForestConfirmSource`** that has the SAME public interface as
`bci.jaw_live.JawConfirmSource`, so both callers switch with a one-line change:

```python
class RandomForestConfirmSource:
    mode: str                      # "wifi" | "dongle" | "synthetic"
    error: Exception | None        # set when the reader thread dies
    def __init__(self, mode: str, port: str | None = None, channels: tuple[int, ...] = (1, 2),
                 model_path: str = "models/clench_model.joblib") -> None: ...  # connects to the board
    def calibrate(self, show: Callable[[str], None]) -> float: ...  # prompts via show(); raises ValueError if unusable
    def start(self) -> None: ...                                    # starts the reader thread
    def take(self) -> bool: ...                                     # True once per recognised clench since last call
    def level(self) -> float | None: ...                            # clench_probability of the newest window, None if bad signal
    def alive(self) -> bool: ...                                    # False once the reader thread died (error is set)
    def stop(self) -> None: ...                                     # stops the thread, releases the board
```

Rules for the implementation:
1. **In-process model, no HTTP in the loop.** Load `clench_model.joblib` with `joblib.load` once in `__init__` and
   call `model.predict_proba` directly. `models/api.py` stays as a debugging tool only: an HTTP round trip per window
   adds latency and a second process that can die.
2. **Same features as training, from the same code.** Move the feature extraction that produced
   `clench_emg_features.csv` into `bci/rf_features.py` as `window_features(window: np.ndarray, fs: float) -> dict`, and
   use it in BOTH the script that writes the CSV and `RandomForestConfirmSource`. Keys must be exactly the model's
   `features` list (the artifact stores it). Commit that script: it is not in the repo today.
3. **Windows:** the same 0.1 s windows as `bci.jaw_live.JawStream` (`WINDOW_S`), on channels 1 and 2 (rows from
   `connect_board`). If the features were trained on a different window length, use that length and say so in the
   module docstring.
4. **Debounce (one clench = one confirm):** fire `take() -> True` once when `clench_probability >= 0.8` for 3
   consecutive windows (0.3 s, same as `bci.jaw.MIN_CLENCH_S`), then a 1.0 s refractory period (same as
   `bci.jaw.REFRACTORY_S`). Tune both numbers on held-out relaxed-breathing data and write the measured false-confirm
   rate in the docstring.
5. **Signal guards stay:** run `bci.jaw.dead_reason(window)` on every raw window; a flat or railed window can never
   confirm and resets the debounce (copy how `JawStream.push` uses `dead_reason` / `mark_dead`).
6. **calibrate(show):** at minimum `show("Relax your jaw, teeth apart (10 s)")`, record, then three
   `show("CLENCH your jaw now (i/3)")` prompts. Use the data to (a) check the model separates THIS rider (median
   probability relaxed < 0.3 and clench > 0.7, else raise `ValueError` with the numbers) and (b) optionally set a
   per-rider probability threshold. Both callers show the prompt strings on screen as they are.
7. **Thread safety:** like `JawConfirmSource`: a daemon reader thread, a `queue.Queue` for events, `take()` drains it.
   Any exception in the thread sets `self.error` (it never dies silently).
8. **Never touch motors.** This class only produces confirm events.

## 3. Wire it in (two one-line swaps)

- `vision/object_select.py` `start_jaw()` (around line 688): construct `RandomForestConfirmSource(args.jaw_board,
  args.jaw_port, channels=parse_channels(args.jaw_channels))` instead of `JawConfirmSource(...)`. Keep the
  `jaw.calibrate(lambda text: show_text(cv2, text))` and `jaw.start()` calls as they are.
- `interface/web/session.py` `real_jaw()` (around line 122): return `RandomForestConfirmSource("wifi", channels=(1, 2))`.

`confirm_event(mode, key, jaw)` and the web session's `_jaw_fired()` already call `jaw.take()`; nothing else in the
drive loop changes. A confirm still needs the gaze to have rested on the object for `MIN_LOOK_S` (0.3 s); keep that.

## 4. Remove every other confirm path (exact list)

`vision/object_select.py`:
- `confirm_event()`: delete the `mode in ("key", "blink")` branch (SPACE / J confirm) and the synthetic `CONFIRM_KEY`
  fake-clench injection; it becomes `return jaw is not None and jaw.take()` (keep the existing log line).
- Delete `CONFIRM_KEY` and the `SPACE = 32` confirm constant (lines ~198-199).
- Delete `BlinkConfirm`, `double_blink()`, `BlinkSeries`, `count_blinks()`, `DOUBLE_BLINK_GAP_S`, `CANCEL_BLINKS`,
  `BLINK_SERIES_S`, and in `run()` the `blink_state` / `series` variables, the `blinked` / `tripled` handling and the
  `if locked and tripled:` triple-blink cancel block (`BLINK_MIN_S` / `BLINK_MAX_CONFIRM_S` too if then unused).
- `confirm_settings()`: delete (dwell confirm is gone); `run()` passes `dwell_s=None` to `update_selection`.
- `--confirm` argparse option: remove it; the only confirm is the BCI. Keep `--jaw-board`, `--jaw-port`,
  `--jaw-channels`.
- `stop_key()` / `KEY_MODE_STOP_KEY`: the emergency stop becomes **S and SPACE** in every mode (SPACE no longer
  confirms, so it is free to stop). Keep the sticky stop: after S/SPACE or X nothing moves (manual arrows included)
  until a NEW clench confirm (`halted` in `run()`).
- `status_line()`: only the BCI wording: "look, then CLENCH to confirm | S stop  X cancel  C re-centre  Q quit".
- `draw()` progress ring: keep the "looked long enough (MIN_LOOK_S)" full ring; remove the dwell-fraction branch.

`demo.sh` and the `Start *.command` files:
- Remove the modes `dwell`, `chair-dwell`, `chair-key`, `mock-key`, `chair-blink`, `mock-blink`, and delete
  `Start dwell.command`, `Start chair-dwell.command`, `Start chair-key.command`, `Start mock-key.command`,
  `Start chair-blink.command`, `Start mock-blink.command`. Keep `jaw` (no motors), `mock` (fake port), `chair`
  (real wheels) and `preview`; all of them use the BCI confirm.

Web app (`interface/web/`):
- `session.py`: delete `_do_confirm`, `Drive.pending_confirm`, `CONFIRM_MODES`; `confirm` is always "jaw".
- `contracts.py`: remove `"confirm"` from `ActionType` and the `confirm` field.
- `frontend/src/main.tsx` `useKeys()`: SPACE, S and Esc = emergency stop; delete the SPACE-confirm branch.
  `frontend/src/drive.tsx`: delete the "Confirm the highlighted object" button and the SPACE-confirm key hint.

Desktop launcher (`interface/launcher_modes.py`): remove the `dwell`, `mock-blink`, `mock-key`, `chair-blink`,
`chair-key` and `chair-dwell` cards.

## 5. Tests (must pass before you push)

- `python -m pytest -q` must stay green. Update or delete the tests that cover removed paths:
  `vision/tests/test_object_select.py` (blink, key and dwell tests), `interface/web/tests/test_web_session.py`
  (`confirm` action), `interface/tests/test_launcher.py` (mode cards).
- New `bci/tests/test_rf_confirm.py` (no hardware: BrainFlow `"synthetic"` board or recorded arrays):
  - relaxed windows (including the 4.5 s breathing rhythm from the 05-15 GUI recording) never fire;
  - a held clench fires exactly once, then nothing during the refractory period;
  - a flat or railed window never fires and resets the debounce;
  - `calibrate()` raises `ValueError` when relaxed and clench probabilities do not separate;
  - a reader-thread exception sets `error` and `alive()` returns False.
- `interface/web/tests/test_chain.py`: swap `synthetic_headset()` to `RandomForestConfirmSource("synthetic", ...)` if
  the synthetic board can produce a confirm through the model; otherwise keep `JawConfirmSource` there and add an
  equivalent chain test that injects recorded clench windows.

## 6. Safety (non-negotiable, from AGENTS.md / docs/SAFETY.md)

- Agents never connect to the real headset or open the ESP32 port; use the synthetic board and recorded files.
- A missing, stale or dead BCI must never confirm: `alive()` False ends the session (the drive loop already stops on
  `not jaw.alive()`).
- Do not lower the debounce below 0.3 s or remove the refractory period without measured false-confirm data.
- Removing SPACE confirm must not remove a stop key: S, SPACE and the STOP button all stop.

## 7. Human acceptance test (Vani + Prakhar, wheels off the ground first)

1. `./demo.sh jaw` (no motors): calibrate, then 10 deliberate clenches while looking at an object -> 10 confirms;
   60 s of talking, breathing and looking around -> 0 confirms. Record both numbers in `PROGRESS.md`.
2. `./demo.sh chair` with wheels up: look + clench -> wheels turn within 0.5 s; S stops at once and nothing moves
   again until the next clench confirm.
3. The same on the floor with a spotter.

Suggested commit message: `feat(bci): random-forest clench confirm replaces SPACE / blink / dwell confirmation`.
