---
name: sprint-close
description: >-
  Close the sprint: full tier, falsifier batch, note triage, retro diff, release.
---

# Sprint Close

`close.py sprint <id>` runs the mechanics; judgment stays here.

0. **Open the sprint first** (once, before its stories). Give a fresh `card-reviewer`
   the full proposed slate, `sprint_cap`, VALUES, JUDGMENT, constraints and system
   context; do not give it the author's conclusions. Check every per-card and slate
   result, record accepted and rejected conclusions with `work.py note`, and correct
   the cards only. With corrected cards: `git switch -c sprint-<id:03d>`, then
   `close.py sprint <id> start`; unfinished output says close checks wait.
1. **Re-run `close.py sprint <id> start` at close** — the same recorded branch is
   a no-op; now it runs the batch and emits the close material.
   A red falsifier ABORTS the close and is re-filed as a bug (JUDGMENT.md carries
   the polarity contract).
2. **Note triage, then the retro — YOURS, and they come FIRST.**
   Promote each note through the retro diff, or archive it. A learning that changes
   nothing executable is not recorded; every promotion displaces something. Write
   the retro and REPLACE the digest: the pipeline emits facts; the
   narrative is the part with judgment.
   BEFORE the review, not after. Land refuses when code moved since the review,
   and a retro that promotes into DESIGN.md, JUDGMENT.md or PROCESS.md is code motion — run it
   last and you must review again, which invalidates what you just wrote.
3. **The review**, which the pipeline marshals — you do not compose it:
   `close.py sprint <id> review`. You receive only what it could not fix.
   Lead changes after a completed round cost a confirming round, except any
   land names as exempt: re-run `close.py sprint <id> review` to get one. That
   run is one story-shaped reviewer over the delta, not another fanout.
   Read the reviewer's diff; land accepts it.
4. **`close.py sprint <id> land`** opens the release PR. Not releasable? Don't run
   it — the branch carries.
5. **`close.py sprint <id> post-merge`**, AFTER the PR merges — it tags. Your
   release artifacts are yours; cut them at step 2 before review.
