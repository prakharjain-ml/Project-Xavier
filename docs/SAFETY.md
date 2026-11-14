# Safety spec (non-negotiable)

A person sits on this chair. Every rule here beats every feature.

## Layers (defense in depth)
1. Hardware kill switch in a human hand during every powered test. Cuts motor power, independent of software.
2. ESP32 bridge: commands zero if the laptop is silent for `BRIDGE_WATCHDOG_MS` (200 ms), stops net forward
   motion (`(left + right) > 0`) on its own when valid ultrasonic distance (`> 0`) is below `OBSTACLE_STOP_CM`,
   and clamps speed again.
3. Control state machine: STOP is the default and the fallback for every unknown. Forward motion is blocked
   (`STOPPED`) whenever obstacle distance is `< OBSTACLE_STOP_CM`, while in-place turns and reverse remain
   available after a fresh dwell so the rider can turn away from the obstacle.
4. Decoder: NONE below the confidence threshold (using absolute SNR/correlation as well as margin so looking
   away drops to NONE within `< 1 s`).
5. Rider: looking away stops the chair (`STOPPED`); closing the eyes puts it into latched `E_STOP`.

## States
| State | Motion | Meaning |
| --- | --- | --- |
| `STOPPED` | none | default at boot, after look-away, after forward obstacle block, and after any stale data |
| `DWELLING` | none | a valid, unblocked target is winning; dwell timer running |
| `MOVING` | mapped command, capped | dwell completed; moving while the same target keeps winning (D1: hold-to-move) |
| `E_STOP` | none (latched) | alpha (eyes closed), operator key, or fault; needs an explicit operator re-arm |

## Transitions (one test per row)
| From | Event | To |
| --- | --- | --- |
| any | exception, unknown state, stale Intent (> `STALE_INTENT_S`) | `STOPPED` |
| any | StopRequest (ALPHA, OPERATOR, FAULT) | `E_STOP` |
| `E_STOP` | operator re-arm key AND no active StopRequest | `STOPPED` |
| any non-`E_STOP` | `target == FWD` AND `0 < distance_cm < OBSTACLE_STOP_CM` | `STOPPED` |
| `STOPPED` | Intent target != NONE, confidence >= threshold, and not forward-blocked by obstacle | `DWELLING` |
| `DWELLING` | same target held for `DWELL_S` with confidence >= threshold and not forward-blocked | `MOVING` |
| `DWELLING` | target changes, NONE, or confidence < threshold | `STOPPED` |
| `MOVING` | same target keeps winning with confidence >= threshold and not forward-blocked | `MOVING` (emit mapped command) |
| `MOVING` | target changes, NONE, or confidence < threshold | `STOPPED` |

## Test protocol (humans run this; agents never do)
1. Wheels off the ground, kill switch in hand, minimum speed.
2. On the floor: clear area at least 3 m, spotter walking beside, minimum speed, then raise the cap slowly.
3. Any uncommanded motion: stop testing, log it in PROGRESS.md, fix and re-test wheels-off first.
4. Never test with a stranger as the wearer. Judges watch; a teammate wears.

## Photosensitivity
Flicker in roughly the 3-30 Hz range can trigger seizures in people with photosensitive epilepsy.
- Ask every wearer and nearby viewer before starting. Warning card at the table.
- Start screen warning; flicker starts only on SPACE.
- Mention it in the pitch: it is part of designing this responsibly.
