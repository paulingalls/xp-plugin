---
name: sprint-close
description: >-
  Close the sprint: full tier, falsifier batch, note triage, retro diff, release.
---

# Sprint Close

`close.py sprint <id>` runs the mechanical steps. Two of them are yours and a
script cannot absorb them (constraint 7).

0. **Open the sprint first** (once, before its stories): `git switch -c sprint-00N`
   and set `sprint_branch: sprint-00N` in `.xp/config.yml`. Step 5 retires the key,
   so every sprint needs this again.
1. **`close.py sprint <id> start`** — appends only; re-running it is a no-op.
   A red falsifier ABORTS the close and is re-filed as a bug (PROCESS.md carries
   the polarity contract).
2. **Note triage, then the retro — YOURS, and they come FIRST.**
   Each note is promoted to constraints.md/system.md via the retro diff, or
   archived. A learning that changes nothing executable is not recorded, and every
   promotion must displace something (constraint 1). Then write the retro
   narrative and the digest: the pipeline emits facts, the narrative is the part
   with judgment in it.
   BEFORE the reviews, not after. Land refuses when code moved since the review,
   and a retro that promotes into DESIGN.md or PROCESS.md is code motion — run it
   last and you must review again, which invalidates what you just wrote.
3. **The two reviews**, which the pipeline marshals — you do not compose them:
   - `close.py sprint <id> review --lens broad` — the sprint as ONE change.
   - `close.py sprint <id> review --lens security` — what it made reachable.
   Fix what they block, then re-run the lens that blocked.
4. **`close.py sprint <id> land`** opens the release PR. Not releasable? Don't run
   it — the branch carries, the key stays.
5. **`close.py sprint <id> post-merge`**, AFTER the PR merges — it tags and
   retires the `sprint_branch` key step 0 sets. Your release artifacts are yours:
   bump and changelog at step 2, because anything outside `.xp/` landing after
   step 3 invalidates the reviews that permit land.
