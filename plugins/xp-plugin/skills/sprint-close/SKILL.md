---
name: sprint-close
description: >-
  Close the sprint: full tier, falsifier batch, note triage, retro diff, release.
---

# Sprint Close

`close.py sprint <id>` runs the mechanical steps. Three of them are yours and a
script cannot absorb them (constraint 7).

0. **Open the sprint first** (once, before its stories): `git switch -c sprint-00N`
   and set `sprint_branch: sprint-00N` in `.xp/config.yml`. Under `release: sprint`
   this is what makes stories integrate on a branch instead of landing on the default
   one — post-merge retires the key at the end, so every sprint needs this step.
1. **`close.py sprint <id> start`** — refuses while any story in THAT sprint is
   unfinished, runs the full tier, then runs every unresolved falsifier in work.md
   and archive.md. A red aborts and is re-filed as a bug: a debt or archived
   falsifier asserts the system is still OK, so red means the latent problem
   materialised. It then emits the notes for triage, the retro skeleton, and the
   digest prompt. It mutates nothing but appends, and re-running it is a no-op.
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
   - `close.py sprint <id> review --lens broad` — the cumulative diff as ONE
     change, at a different altitude from the stories you already reviewed.
   - `close.py sprint <id> review --lens security` — secrets, injection surfaces,
     anything the sprint made reachable that was not before.
   Both are report-only and refuse if the reviewer touches the tree. Re-running a
   lens hands the reviewer that lens's earlier findings to VALIDATE rather than
   re-derive, so a second round is bounded. Fix what they block, then re-run the
   lens that blocked.
4. **`close.py sprint <id> land`** opens the release PR with the proposed version.
   It REFUSES unless both lenses have a round covering HEAD with no blocking
   findings — a release PR over unreviewed commits was bug c9b48a66, measured on
   a real release. Not releasable? Don't run it — the branch carries, the key stays.
4. **`close.py sprint <id> post-merge`**, AFTER the PR merges: cuts the bump and
   the tag on the sha that actually shipped, and retires the `sprint_branch` key.
   Both facts become true in one leg, because a tag cut at PR-open names a commit
   that is not the release.
