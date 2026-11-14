# tools/

**Owner:** anyone

**Purpose:** Development and test helpers that run without hardware.

| In | Out |
| --- | --- |
| - | - |

## Planned files (created during the hackathon, not before)
- fake_eeg.py - synthetic EEG: chosen SSVEP freq + noise + alpha + 60 Hz hum
- record.py - labeled calibration recordings to data/raw/
- analyze.py - offline accuracy, confusion matrix, window sweep
- smoke.py - fake EEG -> decoder -> control -> mock motors end-to-end; must pass before every merge

## Done when
`python tools/smoke.py` exits 0 in under 10 s.

Rules: `.cursor/rules/` (auto-attached for this folder) and `AGENTS.md`. Contracts: `docs/INTERFACES.md`.
