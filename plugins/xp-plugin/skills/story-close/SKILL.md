---
name: story-close
description: >-
  Close the current story: pipeline-spawned review, Verify, merge, digest. Two
  commands with one judgment gap between them.
---

# Story Close

`close.py` runs the mechanical steps. You own exactly one thing: the fix-or-ask
call on the reviewer's findings. Everything else is scripted, and a step you find
yourself doing by hand is a defect in the pipeline — file it.

1. **Preflight**: `git status` clean, and you are on the story branch.
2. **`close.py story <id> review`** spawns the story-reviewer itself and prints its
   ranked findings. The bundle it hands over bases the cumulative diff on the
   INTEGRATION TARGET (the sprint branch under `release: sprint`, else the default
   branch) and carries the reviewer's charter, the story card, the work.md entries
   filed during the story, and constraints.md + system.md. The VERDICT line is
   captured into the close marker — you cannot supply one, and there is no
   `--verdict` flag, because a lead-supplied verdict is forgeable.
3. **Judgment point** (yours, and the only one): fix gating findings now; file
   non-gating ones as bug/debt/note per PROCESS.md; ask the human only where you and
   the reviewer disagree on whether a finding gates.
   Stopping rule: prescription-faithful fixes with red-first tests need no
   re-review; two rounds maximum, then escalate to the human.
4. **`close.py story <id> land`** runs the story's Verify and the story tier, merges
   under every recorded verdict, flips the card to `[done]`, pushes the integration
   branch, deletes the story branch (local first, then origin), and logs the close.
   A red Verify aborts before the merge. If you committed anything after step 2,
   land refuses and re-reviews the delta in-pipeline — read those findings and run
   land again.
5. **Write the session digest** (≤30 lines: intent, surprises, next step). You are
   its sole writer — the pipeline records the facts of the close, never the
   narrative.
