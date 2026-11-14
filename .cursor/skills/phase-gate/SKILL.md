---
name: phase-gate
description: Check whether the current phase's gate in the master plan has passed, with evidence. Use at the end of each phase or at a team sync.
disable-model-invocation: true
---

# Phase gate check

1. Read `.cursor/plans/ssvep-chair.plan.md` and find the current phase from the team board in `PROGRESS.md`.
2. List every "Done when" item and the Gate line for that phase.
3. For each item, gather evidence by running the relevant non-hardware command (pytest for the folder,
   `python tools/smoke.py`, or the module with `--synthetic`/`--mock`). Never run anything that opens a serial port.
   Items that need hardware or a human (wheels-off test, phone video): mark "needs human" and say exactly what to check.
4. Output a table: item | status (pass / fail / needs human) | evidence (command + key output line).
5. Verdict: GATE PASSED or GATE NOT PASSED. If not passed and the plan lists a fallback, name it.
6. Append the verdict and date-time to the Gate log in the team board section of `PROGRESS.md`. Change nothing else.
