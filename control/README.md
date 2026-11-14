# control/

**Owner:** Prakhar (design), Pratosh (integration)

**Purpose:** Decide what the chair does every tick. STOP unless everything says go.

| In | Out |
| --- | --- |
| `Intent`, `StopRequest`, obstacle distance | `MotorCommand` at `CONTROL_HZ`, `ControlStatus` |

## Planned files (created during the hackathon, not before)
- state_machine.py - states and transitions from docs/SAFETY.md
- mapping.py - target -> wheel speeds, capped
- tests/ - one test per SAFETY.md transition + low-confidence fuzz test

## Done when
Every SAFETY.md transition has a passing test; fuzz test never produces motion.

Rules: `.cursor/rules/` (auto-attached for this folder) and `AGENTS.md`. Contracts: `docs/INTERFACES.md`.
