---
name: story-close
description: >-
  Close the current story: fresh-context review, Verify, merge, digest. This
  checklist is the spec for close.py (story-002); run it by hand until then.
---

# Story Close (manual checklist — the spec for close.py)

1. **Preflight**: story branch pushed; `git status` clean; story's AC list open.
2. **Spawn the story-reviewer** (Agent tool, `story-reviewer`) on the bundle
   `close.py story <id> start` emits: it bases the cumulative diff on the
   INTEGRATION TARGET (the sprint branch under `release: sprint`, else the default
   branch) and carries the story card, the work.md entries filed during the story,
   and constraints.md + system.md. Wait for its ranked findings + VERDICT line.
3. **Judgment point** (yours): fix gating findings now; file non-gating ones as
   bug/debt/note per PROCESS.md; ask the human only where reviewer and you disagree
   on gating.
4. **Run the story's Verify commands** from its card, then the story test tier.
   Red aborts the close.
5. **Open the PR / merge**, with the reviewer's VERDICT line verbatim in the PR body
   (or merge-commit trailer). If the merge conflicts or files outside the reviewed
   diff changed, return to step 2 with the post-resolution diff.
   Stopping rule: prescription-faithful fixes with red-first tests need no
   re-review; two rounds maximum, then escalate to the human.
6. **Mark the story done** in .xp/plan.md; update the ≤30-line session digest
   (intent, surprises, next step) — you are its sole writer.
