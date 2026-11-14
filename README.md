# SSVEP BCI Wheelchair (HackPrinceton F26)

Drive a wheelchair by looking at flickering arrows. Look away or close your eyes and it stops.

Status: planning workspace. Project code is written during the hackathon (from Fri Nov 13, 8:00 pm).

## Start here
| If you are | Read |
| --- | --- |
| A teammate | `docs/PRD.md`, then `.cursor/plans/ssvep-chair.plan.md`, then your folder's README |
| A coding agent | `AGENTS.md` (Cursor also loads `.cursor/rules/` automatically) |
| Picking up someone's work | `PROGRESS.md` |
| New to how we use agents | `docs/VIBECODING.md` |

## Open in Cursor (2 minutes)
1. Open this folder in Cursor.
2. Check rules load: Cursor Settings > Rules should list the `.cursor/rules` files; ask the agent
   "What is the default motor command and which folder may you edit?" (Answer: STOP, only the one you name.)
3. Check skills: type `/` in Agent chat; you should see `handoff`, `phase-gate`, `review-diff`, `explain-back`.
4. Check the hook: Cursor Settings > Hooks should show `beforeShellExecution`. Run `chmod +x .cursor/hooks/guard.sh` once.
5. Start a phase: switch to Plan mode, attach `.cursor/plans/ssvep-chair.plan.md`, say
   "Make the plan for Phase 1 only", then save it to the workspace.

## Run (once the code exists)
```
source ~/venvs/hp26/bin/activate
python tools/smoke.py                      # end-to-end on fake data, no hardware
python app.py --synthetic --mock           # full app, fake EEG, mock motors
python app.py --cyton --serial /dev/cu.X   # humans only, kill switch in hand
```

## Team
Keshav (hardware), Pratosh (motors/integration), Vani (software/vision), Prakhar (interface, safety logic, demo).
