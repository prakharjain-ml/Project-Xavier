# How we vibecode (team playbook, Nov 2026)

Built from current X posts (Oct-Nov 2026) and Cursor's docs. The one-line version, from a post with ~950 likes:
juniors send one big prompt and debug slop all day; seniors configure rules and memory, add skills, test the
agent, write a PRD, plan tasks, assign focused pieces, and build a working MVP before polishing.
([@The_AliQ](https://x.com/The_AliQ/status/2117194890039988614))

## 1. The files come first (done: this repo)
PRD, architecture, design/rules, tasks, progress. "No files = the AI guesses."
([@suraj_sharma14](https://x.com/suraj_sharma14/status/2119640364466532839))
Our mapping: `docs/PRD.md`, `docs/ARCHITECTURE.md`, `docs/INTERFACES.md`, `.cursor/rules/`,
`.cursor/plans/ssvep-chair.plan.md`, `PROGRESS.md`.

## 2. The goal is the contract
Keep one source of truth for behaviour, constraints and acceptance criteria; give the reviewer the same criteria;
persist decisions and evidence, not whole conversations; every result needs a destination; enforce permissions in
tools, not prompts. ([@_mayurc, six rules](https://x.com/_mayurc/status/2118818552765436398))
Our mapping: Mode 1 acceptance criteria in PRD; phase gates in the plan; evidence lines in PROGRESS.md;
`.cursor/hooks.json` blocks motor and destructive commands.

## 3. Karpathy's failure list, turned into rules
Agents assume instead of asking, write 1,000 lines when 100 would do, and change code you never asked them to
touch. ([via @RoundtableSpace](https://x.com/RoundtableSpace/status/2115009357142266115))
Our mapping: rules 4 and 5 in AGENTS.md and `00-core.mdc`.

## 4. Spec before code
GitHub's Spec Kit is trending (~120K stars) for one reason: it forces spec -> plan -> tasks before
implementation. ([@robiartec](https://x.com/robiartec/status/2116534034813665564))
We do the same lighter-weight: master plan -> per-phase Cursor plan -> tasks -> build. Spec Kit itself is too much
ceremony for 36 hours.

## 5. Cursor features we use (and skip)
| Feature | Use it for | Notes |
| --- | --- | --- |
| Plan mode | Start of every phase | Plans save to `~/.cursor/plans/` by default; "save to workspace" puts them in `.cursor/plans/` with the Build button. A hand-written .plan.md has no Build button, so ask Plan mode to plan from the master plan |
| Agents Window + worktrees | One agent per folder in parallel | No two agents on the same files |
| Project rules `.cursor/rules/*.mdc` | Always-on core + per-folder rules | Frontmatter: description, globs, alwaysApply. Plain .md in that folder is ignored |
| AGENTS.md | Shared instructions for every tool | Cursor reads root and nested AGENTS.md |
| Skills `.cursor/skills/*/SKILL.md` | `/handoff`, `/phase-gate`, `/review-diff`, `/explain-back` | Type `/` in chat |
| Hooks `.cursor/hooks.json` | Block serial/motor and destructive commands | Deterministic, unlike rules |
| `/visualize` | EEG plots, confusion matrices in Phase 3 | Charts inline in the Agents Window |
| Projects (multiplayer, beta since Nov 10) | Maybe: shared task board for the team | Runs on cloud agents, which cannot reach our EEG board, motors or camera. Don't depend on a beta during the build |
| Cursor iOS remote control | Skip | iOS only |

Security note: on Oct 30 Cursor reported a malicious modified "Claude Code" extension in its extension marketplace
([@cursor_ai](https://x.com/cursor_ai/status/2116074289053175808)). Install extensions only from the verified
publisher, and check after installing.

## 6. Model routing in Cursor (prices from @cursor_ai, Nov 2026)
| Job | Model | Why |
| --- | --- | --- |
| Hard reasoning: decoder accuracy, weird bugs, state machine design | Claude Fable 5.2, default effort first | Top on CursorBench at max effort (60%), 56.9% at default; $8/$40 per M tokens. Cursor says start at default effort ([post](https://x.com/cursor_ai/status/2119880841728000057)) |
| Second opinion / reviewer | Gemini 4 Carbon (high) | Top CursorBench 60.4% at high; 50% off through Nov 30 ([post](https://x.com/cursor_ai/status/2120193584670580857)). Different model family than the author catches more |
| Everyday implementation | Opus 5.5, Sonnet 5.5 or Gemini 4 Argon | Argon on par with Opus 5.5 at $2/$10 ([post](https://x.com/cursor_ai/status/2110087611763368271)) |
| Cheap and fast: boilerplate, docs, tests | DeepSeek V4.1 Flash, Haiku 5.5, Gemini 4 Hydrogen | Pennies per task |
Rule of thumb: the author model and the reviewer model are always different families.

## 7. The loop for every task
1. **Explain**: "Read the plan section and the folder README. Explain the approach in plain English. Wait."
2. **Plan**: 3-6 bullets, or Plan mode for multi-file work. Edit the plan before building.
3. **Build one step**: "Do step 1 only. Stop and show output."
4. **Prove**: command + real output, a test, a plot, a phone video. Never "should work".
5. **Understand**: "Walk me through it in chunks. Ask me one question to check I understood."
6. **Review**: `/review-diff` with a different model.
7. **Commit + handoff**: `/handoff`, then push.

Two loops on the same bug = stop. Commit what works, switch model, or ask a teammate.

## 8. Agent ran out mid-task (5 minutes)
1. If it has any quota left: `/handoff`. Otherwise write 3 lines in PROGRESS.md yourself.
2. `git add <your folder> PROGRESS.md && git commit -m "wip(<folder>): handoff" && git push`
3. Switch model in Cursor, or open Claude Code / Codex in the repo root.
4. "Read AGENTS.md, the current phase in the plan, my PROGRESS.md section, `git log -5 --stat`.
   Tell me the state and the single next step in 5 bullets. Don't edit yet."
5. Check it, correct it, then "Do only that step."

## 9. Git habits for 4 people
- `main` always runs `python tools/smoke.py`. One branch per folder; merge every 1-2 hours.
- `git add <your folder>`, never `git add .` after kickoff. Never force-push main.
- Tag demo-ready states: `git tag demo-ok-N`.
- Note on macOS Python env (`~/venvs/hp26`): use `opencv-python-headless` rather than `opencv-python`, and keep `cv2`
  confined to the separate Mode 2 `vision/` process (D3) so SDL2 symbols never collide with `pygame` in Mode 1. Pre-cached
  YOLO weights live in `~/hp26-models/`.
