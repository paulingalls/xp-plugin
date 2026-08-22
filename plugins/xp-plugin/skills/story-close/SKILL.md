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
2. **`close.py story <id> review`** spawns the story-reviewer, which FIXES what it
   finds in your tree and commits. Reading its diff is your judgment point; running
   land is how you accept it.
   DOES NOT EXIST, so do not go looking: a delta review, a flag by which you supply
   a finding yourself, a round recorded without the reviewer's own report.
3. **Judgment point** (yours, and the only one): fix blocking findings now; file the
   noted ones as bug/debt/note per PROCESS.md; ask the human only where you and the
   reviewer disagree on whether a finding blocks. YOU choose the rounds — running
   review again is the only thing that starts one. Stopping rule: the REVIEWER's fixes
   cost no confirming round — they are inside the round that found them, and your read
   of its diff is the judgment. YOUR fixes move HEAD past what the review covered, so a
   lead fix batch costs one confirming round. What ends the rounds is the finding
   bar — silent or corrupting earns another, loud does not — never a count.
4. **`close.py story <id> land`** — deterministic, and it never spawns. Run it from
   the story worktree: it merges in whichever tree holds the integration branch, so
   YOUR SHELL IS LEFT IN A DELETED DIRECTORY. Every refusal names its own next
   action; run it twice and you get the same answer.
5. **Write the session digest** (≤30 lines: intent, surprises, next step). You are
   its sole writer — the pipeline records the facts of the close, never the
   narrative.
