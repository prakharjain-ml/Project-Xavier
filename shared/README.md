# shared/

**Owner:** Prakhar

**Purpose:** One definition of every message and constant.

| In | Out |
| --- | --- |
| docs/INTERFACES.md | `protocol.py` imported by every folder |

## Planned files (created during the hackathon, not before)
- protocol.py - frozen dataclasses, enums, constants; generated at kickoff from docs/INTERFACES.md

## Done when
Every folder imports from here; nothing redefined locally.

Rules: `.cursor/rules/` (auto-attached for this folder) and `AGENTS.md`. Contracts: `docs/INTERFACES.md`.
