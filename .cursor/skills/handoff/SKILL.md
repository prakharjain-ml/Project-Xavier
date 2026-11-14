---
name: handoff
description: Write a clean handoff for the next agent or teammate. Use before switching models, when quota runs low, before sleep, or before merging.
disable-model-invocation: true
---

# Handoff

1. Identify the folder you worked in this session.
2. Update ONLY that folder's section of `PROGRESS.md`, newest entry first:
   - Done (with file:function names)
   - In progress (file:function and its exact state, including anything half-written)
   - Next step (one concrete action a fresh agent can start immediately)
   - Known bugs
   - Evidence (the last command run and its real output, shortened)
3. Run `git status` and list uncommitted files.
4. Propose one commit command that stages only that folder and PROGRESS.md, with a conventional message.
5. Do not push. Do not edit any other file.
6. Finish with: "A fresh agent should start by: <the next step>".
