---
name: sprint-close
description: >-
  Close the sprint: full tier, falsifier batch, note triage, retro diff, release.
---

# Sprint Close

`close.py sprint <id>` runs the mechanics; judgment stays here.

1. **Re-run `close.py sprint <id> start` at close** — the same recorded branch is
   a no-op; now it runs standalone falsifiers and emits open debts, unresolved findings, notes and the retro
   template. A red falsifier ABORTS the close and is re-filed as a bug
   (JUDGMENT.md carries the polarity contract). Land runs the full tier and
   its deferred falsifiers on the shipping tree.
2. **Triage, then the retro — YOURS, and they come FIRST.**
   Every open debt and unresolved finding: fix now, explicitly drop with a reason,
   or exceptionally keep with BOTH JUDGMENT bars restated (`work.py keep --ref ID
   --too-big '...' --too-important '...'`). Drop debt with `work.py archive --ref ID
   --disposition 'dropped: <reason>'`. Judge legacy/untriaged findings and notes
   containing deferred findings; never silently relabel them. For review-history
   findings, write a fresh schema-2 disposition report, then `work.py judge --source
   '<marker-path or closes.jsonl:LINE>' --report /absolute/judgment.json`; this links
   the judgment to its source without rewriting history or waiving land blockers.
   A wrong judgment is withdrawn with `work.py archive --ref ID --disposition
   'withdrawn: <reason>'`. Check that each debt reference covers its finding; only
   the lead judges meaning.
   Genuine discovery
   and value-tradeoff notes are promoted through the retro diff or archived. Then
   decide which offered resolved records to archive, knowing that disposal
   forfeits their replacement falsifier's recurring guarantee. Then
   `work.py compact` once. A learning that changes nothing executable is not
   recorded; every promotion displaces something. Write
   the retro and REPLACE the digest: the pipeline emits facts; the
   narrative is the part with judgment.
   BEFORE the review, not after. Land refuses when code moved since the review,
   and a retro that promotes into a project design document, JUDGMENT.md or PROCESS.md is code motion — run it
   last and you must review again, which invalidates what you just wrote.
3. **The review**, several stages the pipeline marshals — you do not compose it:
   `close.py sprint <id> review`. Read every disposition. Fix by default, reasoned drop or exceptional debt with
   both bars; unmet ACs and release blockers still require a fix. Escalate reserved
   choices. The report preserves decisions from every stage.
   Lead changes after a completed round cost a confirming round, except any
   land names as exempt: re-run `close.py sprint <id> review` to get one. That
   run is one story-shaped reviewer over the delta, not another fanout.
   Read the reviewer's diff; land accepts it.
4. **`close.py sprint <id> land`** opens the release PR. Not releasable? Don't run
   it — the branch carries.
5. **`close.py sprint <id> post-merge`**, AFTER the PR merges. Your
   release artifacts are yours; cut them at step 2 before review.
