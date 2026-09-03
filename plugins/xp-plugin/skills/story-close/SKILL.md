---
name: story-close
description: >-
  Close the current story: spawned review, Verify, merge, digest.
---

# Story Close

`close.py` runs the mechanical steps. You own exactly one thing: the fix-or-ask
call on the reviewer's findings. Everything else is scripted, and a step you find
yourself doing by hand is a defect in the pipeline — file it.

1. **Preflight**: `git status` clean, and you are on the story branch.
2. **Read the round `spawn` already recorded** — the reviewer was its fourth stage.
   Run `close.py story <id> review` only if the tree moved since; by reflex it spends
   a second full reviewer on a diff already reviewed. The leg spawns the
   story-reviewer, which FIXES what it finds in your tree and commits. Reading its
   diff is your judgment point; running land is how you accept it.
   DOES NOT EXIST, so do not go looking: a delta review, a flag by which you supply
   a finding yourself, a round recorded without the reviewer's own report, a refusal
   because trunk moved (only files trunk and your story BOTH changed cost a round).
3. **Judgment point** (yours, and the only one): fix blocking findings; file noted
   ones per JUDGMENT.md; ask the human only where you and the reviewer disagree.
   Stopping rule: the REVIEWER's fixes cost no confirming round — inside the round
   that found them, and your read of its diff is the judgment. YOUR fixes move HEAD
   past what the review covered and still cost one confirming round — land REPORTS
   that delta now rather than refusing, so this half is yours to honour. What ends
   the rounds is the finding bar — silent or corrupting earns another, loud does
   not — never a count.
4. **`close.py story <id> land`** — deterministic, and it never spawns. Run it from
   the story worktree: it merges in whichever tree holds the integration branch, so
   YOUR SHELL IS LEFT IN A DELETED DIRECTORY. Every refusal names its own next
   action; run it twice and you get the same answer.
5. **REPLACE the session digest** (≤30 lines: intent, surprises, next step) —
   rewritten, never appended to. You are its sole writer; the pipeline records
   the facts, never the narrative.
