---
name: review-diff
description: Read-only code review of the current branch against main, focused on bugs, safety and contract violations. Use before merging to main, ideally with a different model than the author.
disable-model-invocation: true
---

# Review diff (read-only)

Do not edit any file in this skill.

1. Run `git diff main...HEAD --stat` and `git diff main...HEAD`.
2. Check, in this order:
   - Safety: any path that could produce motion without a confident, fresh, dwelled Intent; missing STOP fallbacks;
     any code that opens a serial port outside `motors/driver.py`.
   - Contracts: types or constants defined locally instead of imported from `shared/protocol.py`; changes that
     contradict `docs/INTERFACES.md` or `docs/SAFETY.md`.
   - Scope: files changed outside the owner's folder.
   - Correctness: off-by-one in windows/frames, wrong units, `time.time()` used for intervals, blocking calls in the
     pygame loop, missing tests for new behaviour.
   - Size: code that could be a third as long.
3. Output a numbered list: severity (blocker / should-fix / nit), file:line, the problem, the suggested fix.
4. End with MERGE OK or DO NOT MERGE.
