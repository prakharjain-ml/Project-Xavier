# Project Xavier: gaze-steered wheelchair (HackPrinceton F26)

The rider looks at an object on the laptop screen (webcam gaze tracking) and confirms by holding the gaze 1.5 s or by
a jaw clench read through an OpenBCI headset. The chair then drives toward it while the rider keeps looking at it.
Looking away stops it. The original plan was steering by flickering arrows and brain signals (SSVEP); that part was
not finished: only the flicker screen exists, and there is no SSVEP decoder and no closed-eyes stop.

Status: hackathon code. Which pieces are proven on hardware: `docs/PROJECT_CONTEXT.md` section 8 and `PROGRESS.md`.

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

## Run
```
source ~/venvs/hp26/bin/activate
python -m pytest -q                                    # all tests, no hardware
python app.py --keyboard --mock                        # arrows, arrow keys stand in for the rider, fake motors
python app.py --gaze --mock                            # arrows by gaze, fake motors
python -m vision.object_select --drive --mock          # look at an object, confirm, drive into a fake port
python -m vision.object_select --drive --serial /dev/cu.X   # humans only, kill switch in hand
```
`tools/smoke.py` and the `--synthetic` and `--cyton` flags of `app.py` do not exist.

## Team
Keshav (hardware), Pratosh (motors/integration), Vani (software/vision), Prakhar (interface, safety logic, demo).
