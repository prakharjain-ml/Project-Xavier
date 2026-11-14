# bci/

**Owner:** Vani

**Purpose:** Turn raw EEG into an Intent: which target the wearer is looking at, and how sure we are.

| In | Out |
| --- | --- |
| BrainFlow stream (synthetic or Cyton) | `Intent`, `StopRequest(ALPHA)` |

## Planned files (created during the hackathon, not before)
- acquire.py - BrainFlow wrapper, `--synthetic` / `--cyton`
- filters.py - band-pass + 60 Hz notch, zero-phase
- ssvep.py - FFT-power and CCA scorers (f and 2f)
- decoder.py - sliding window -> scores -> Intent with confidence
- alpha.py - eyes-closed detector -> StopRequest
- tests/ - recover each frequency from synthetic data; harmonic test; noise -> NONE

## Done when
Both scorers pick the right target in at least 95% of synthetic windows (Phase 2); live accuracy at least 80% (Phase 3).

Rules: `.cursor/rules/` (auto-attached for this folder) and `AGENTS.md`. Contracts: `docs/INTERFACES.md`.
