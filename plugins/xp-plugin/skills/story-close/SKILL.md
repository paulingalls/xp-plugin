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
   ranked findings. The bundle bases the cumulative diff on the INTEGRATION TARGET
   (the sprint branch under `release: sprint`, else the default branch) and carries
   the charter, the story card, the work.md entries filed during the story, and
   constraints.md + system.md. The reviewer writes `{fixed, blocking, noted}` to a
   round-scoped report file the bundle names; that report is the only thing recorded,
   and no report means no round. Every round covers the whole story diff — there is no
   delta review, and no flag by which you can supply a finding yourself.
   If the integration branch has moved ahead of your fork point, review refuses and
   asks you to merge it in first: re-reviewing without that leaves the merge base
   where it was, so the reviewer never sees what land would merge.
3. **Judgment point** (yours, and the only one): fix blocking findings now; file the
   noted ones as bug/debt/note per PROCESS.md; ask the human only where you and the
   reviewer disagree on whether a finding blocks. YOU choose the rounds — running
   review again is the only thing that starts one. Stopping rule: prescription-faithful
   fixes with red-first tests are owed no further round of FINDINGS — but a fix moves
   HEAD, and land requires the last review to cover HEAD, so a fix batch costs one
   confirming round. Two rounds of findings maximum, then escalate to the human.
4. **`close.py story <id> land`** is deterministic and spawns nothing. It refuses
   while the last round has blocking findings, while HEAD has moved since the review
   you were shown, or while the recorded round does not cover this tree — naming the
   review command each time, so running it twice gives the same answer. Otherwise it
   runs the story's Verify and the story tier, merges under every round labelled by
   its number, flips the card to `[done]`, pushes the integration branch, deletes the
   story branch (local first, then origin), and logs the close. A red Verify aborts
   before the merge.
5. **Write the session digest** (≤30 lines: intent, surprises, next step). You are
   its sole writer — the pipeline records the facts of the close, never the
   narrative.
