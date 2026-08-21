---
name: sprint-close
description: >-
  Close the sprint: full tier, falsifier batch, note triage, retro diff, release.
---

# Sprint Close

`close.py sprint <id>` runs the mechanical steps. Three of them are yours and a
script cannot absorb them (constraint 7).

1. **`close.py sprint <id> start`** — refuses while any story in THAT sprint is
   unfinished, runs the full tier, then runs every unresolved falsifier in work.md
   and archive.md. A red aborts and is re-filed as a bug: a debt or archived
   falsifier asserts the system is still OK, so red means the latent problem
   materialised. It then emits the notes for triage, the retro skeleton, and the
   digest prompt. It mutates nothing but appends, and re-running it is a no-op.
2. **Your three judgment steps**, in order:
   - **Note triage** — each note is promoted to constraints.md/system.md via the
     retro diff, or archived. A learning that changes nothing executable is not
     recorded, and every promotion must displace something (constraint 1).
   - **The broad review** — read the sprint's cumulative diff as one change, not as
     the stories you already reviewed. Different altitude, different findings.
   - **The LLM security review** — secrets, injection surfaces, anything the
     sprint made reachable that was not before.
   Then write the retro narrative and the digest yourself. The pipeline emits
   facts; the narrative is the part with judgment in it.
3. **`close.py sprint <id> land`** opens the release PR with the proposed version.
   Not releasable? Don't run it — the branch carries and the key stays.
4. **`close.py sprint <id> post-merge`**, AFTER the PR merges: cuts the bump and
   the tag on the sha that actually shipped, and retires the `sprint_branch` key.
   Both facts become true in one leg, because a tag cut at PR-open names a commit
   that is not the release.
