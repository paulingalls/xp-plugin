---
name: story-close
description: Close the current story with independent review, one conditional fix and closure, and landing.
---

# Story Close

Read the completed review sequence and its retained reports from spawn; judge every finding under JUDGMENT.md: fix by default, explicitly drop with a reason, or
retain exceptional debt with a real record reference and both bars. Reserved choices
and unmet ACs belong to the lead; dispositions cannot waive release blockers.

If correction changes the solution, commit it and run `close.py story <id> review`
to explicitly authorize a new sequence. For incomplete producer output, the same
command corrects that producer while retaining completed stages and commits.
`spawn.py resume <id>` resumes interrupted validation. A green same-tree retry still
needs `close.py story <id> acknowledge-validation --reason '<observed cause>'` from
the lead before completion. Inspect the retained red and green evidence first.

Run `close.py story <id> land` from the story worktree after the sequence completes.
It runs deterministic gates and moves refs. Replace the session digest (≤30 lines) with intent,
surprises and the next step. Automatic reviewer/fixer/closer retry and separate
repair/salvage routes do not exist.
