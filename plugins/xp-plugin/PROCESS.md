# Process

One page. The values (VALUES.md) cover what this page doesn't.

## The loop

Three skills carry the judgment the scripts cannot: **`/xp-setup`** scaffolds a
project once, **`/story-close`** closes a story, **`/sprint-close`** closes a
sprint. Run them rather than the scripts they wrap — the steps are in the script,
the decisions are only in the skill.

1. **Plan** — any multi-file change.
   - Draft the plan to a file, then run the **plan-reviewer**: it checks TDD
     ordering, coherence, constraints and sprint size, edits addressable problems
     into the plan with reasons, and stops on human-only questions.
   - Re-read it, then `spawn.py ready <story-id>`: flips `[planned]` → `[ready]`
     and records a digest of the card. Spawn recomputes that digest, so a card
     edited afterwards refuses with the diff. The bracket is display; the digest is
     the credential — it binds the text you reviewed, it cannot know you read it.
2. **Story** — red → green → refactor, small commits.
   - Done = ACs verified against the running system at its surface (the story
     loop), not "tests green" (the commit loop). Two loops, two clocks.
   - Git hooks are the wall: lint, secrets and fast tests at commit; lint, secrets,
     full tests and the ratchet at push. Push re-checks the commit gates because a
     skipped hook leaves no trace, and every gate here is a pure function of the
     tree. Never fake a red — a config/docs commit says so in its body.
   - Comments: restates the code → delete · explains WHAT → rename it · a checkable
     claim → write the test · narrates history → delete, git holds it. Keep only the
     why, an external constraint, a rejected design.
3. **Story close** — run **`/story-close`**.
   - It spawns the **story-reviewer** on the cumulative diff plus anything you
     filed in work.md, stops for your fix-or-ask call, runs the story's Verify,
     records every round in the merge body, and merges.
   - Review and merge are separate commands. Land never spawns: on drift or a
     conflict it refuses and names the review leg, so a round is something you
     choose to run, not something a merge inflicts.
   - **Stopping rule**: one full review always. A REVIEWER fix is inside the round
     that found it — reading its diff is your judgment. A LEAD fix moves HEAD past
     what the review covered and costs one confirming round; land REPORTS that
     delta rather than refusing, so this half is yours to honour.
   - Faithful means SCOPE-IDENTICAL: generalizing a prescription is a deviation,
     and deviations, uncovered behavior and conflict resolutions are owed a round.
   - What ENDS a round is the finding bar, never a count: a finding earns another
     round only if its failure mode is silent or corrupting (false green, corrupted
     record, unreviewed merge). Loud and patch-scale → fix it now if that is
     minutes, else file it.
4. **Sprint close** — run **`/sprint-close`** (release: sprint, the default).
   - Stories integrate on the sprint branch; the batch PRs to trunk when RELEASABLE
     — usually now (keep sprints small). Prefer flags that dark-launch unready work.
   - ORDER MATTERS: falsifier batch and full tier, then note triage and the retro,
     then `review` LAST. The retro promotes into constraints/DESIGN/PROCESS, which
     is code motion — after the review it invalidates the review that permits land.
   - The retro is a narrative plus a proposed diff. A learning that changes nothing
     executable is not recorded, and the narrative is PRESENTED, never just filed.
   - Debt triage with the human under the same bar. Loud + self-healing → NEVER:
     everything is fail-loud, so a never that later matters returns as a red. Never
     is a decision, not a backlog — schedule under budget or drop; nothing carries.

## Records (work.md — via the append CLI)

- **bug** — claim + falsifier that reds NOW + files. A DEFECT is a bug: if you called
  it one, the rule below is the one you are under. Fix immediately; the red is what
  bounds "now". Can't red? It's not a bug — file debt or a note, and say which.
- **debt** — claim + falsifier (currently green) + files. Considered only at sprint
  planning: scheduled or dropped to archive. Never scheduled mid-sprint unless it
  blocks the current story's acceptance (which makes it a bug).
- **Polarity**: a debt or archived falsifier asserts the system is still OK. Red means
  the latent problem materialised. One that greens BECAUSE the flaw is present is
  inverted, and aborts the sprint close on the day someone fixes it.
- **resolve** — substitutes a falsifier that must be green NOW; the batch runs the
  replacement, so a wrong resolution reds later and the record reopens. Records are named by id
  (`work.py list`), never by timestamp — appends can share a second.
- **note** — decisions (choice + because, naming which value won and which lost)
  and discoveries. Triaged at SPRINT close: promoted to constraints.md, or archived.
  A directive the next story must FOLLOW goes on that story's CARD; the note keeps
  the evidence.

Telemetry (test/lint failures) is never recorded — the gate re-measures next run.

## Session continuity

The plan's story states + git + work.md are the memory. REPLACE the session digest
at story/sprint close only — never append; SessionStart refuses over the bound and
names it. On start: trust it, verify against the artifacts — artifacts win.
