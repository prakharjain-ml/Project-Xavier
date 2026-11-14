# interface/

**Owner:** Prakhar

**Purpose:** Show the flickering targets at exact frequencies and give the wearer feedback.

| In | Out |
| --- | --- |
| `TARGET_FREQS_HZ`, `ControlStatus`, `TargetSet` (Mode 2) | Pixels on screen; frame-timing log |

## Planned files (created during the hackathon, not before)
- flicker.py - pygame main loop, frame-counted flicker, FPS + dropped-frame counter
- widgets.py - target, dwell bar, warning screen
- tests/ - frequency-to-frame math, reject invalid frequencies

## Done when
60 FPS for 60 s, zero dropped frames on the demo laptop; slow-motion phone video confirms frames per cycle.

Rules: `.cursor/rules/` (auto-attached for this folder) and `AGENTS.md`. Contracts: `docs/INTERFACES.md`.
