# Process

One page. The values (VALUES.md) cover what this page doesn't.

## The loop

1. **Plan** (any multi-file change): draft the plan, then spawn the **plan-reviewer**
   (fresh context — it owes your plan nothing). A card starts `[planned]` and the
   review is what clears it to `[ready]`, which is the only state spawn accepts —
   so address the findings before implementation code. It checks TDD ordering,
   artifact coherence, constraint conflicts, and sprint size.
2. **Story**: red → green → refactor, small commits. Done = ACs verified against
   the running system at its surface (the story loop), not "tests green" (the
   commit loop) — two loops, two clocks. Git hooks are the wall: lint,
   secrets, fast tests at commit; full tests at push. Never fake a red — a config/docs
   commit says so in its body instead.
   Comments: restates the code → delete · explains WHAT → rename it · a checkable
   claim → write the test · narrates history → delete, git holds it. Keep only the
   why, an external constraint, a rejected design.
3. **Story close**: run the `/story-close` checklist — it spawns the **story-reviewer**
   on the cumulative diff plus anything you filed in work.md, stops for your
   fix-or-ask call, runs the story's Verify commands, records every review round in
   the merge body, and merges. Review and merge are separate commands: land never
   spawns — on drift or a conflict it refuses and names the review leg, so a round is
   something you choose to run, not something a merge inflicts.
   **Review stopping rule** (diminishing returns): one full review always. A
   REVIEWER fix costs nothing extra — it is inside the round that found it, and your
   read of its diff is the judgment. A LEAD fix moves HEAD past what the review
   covered, so it costs one confirming round; that is why fix batches are batches.
   Faithful means SCOPE-IDENTICAL — generalizing a prescription is a deviation, and
   deviations, new uncovered behavior and conflict resolutions are owed a real round.
   Uncertain? One delta ping beats a wrong self-call. What ENDS a round is the
   finding bar, not a count: a finding earns another round only if its failure mode
   is silent or corrupting (false green, corrupted record, unreviewed merge). Loud
   and patch-scale → fix it now if that is minutes, else file it.
4. **Sprint close** (release: sprint — the default): stories integrated on the
   sprint branch throughout; the batch PRs to main when it is RELEASABLE —
   usually now (keep sprints small), else carried to the plan boundary; prefer
   flags that dark-launch unready behavior over holding the branch. Archived
   falsifiers batch-run + full tier + note triage + retro (one-page narrative + a
   proposed diff to constraints/config — a learning that changes nothing executable
   isn't recorded; the narrative is PRESENTED to the human at close, never just
   filed), then `review --lens broad|security` LAST, or the retro invalidates the
   review that permits it. Debt triage with the
   human, under the **finding bar**: a finding earns work only if its failure mode is
   silent or corrupting (false green, corrupted record, unreviewed merge). Loud +
   patch-scale → fix now only if minutes. Loud + self-healing → NEVER — everything
   here is built fail-loud, so a never that later matters returns as an
   evidence-bearing red. Never is a decision, not a backlog: schedule under budget
   or drop; nothing carries.

## Records (work.md — via the append CLI)

- **bug** — claim + falsifier that reds NOW + files. Fix immediately; the red is what
  bounds "now". Can't red? It's not a bug.
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

`plan.md` story states + git + work.md are the memory. Write the ≤30-line session
digest at story/sprint close only. On start: trust the digest, verify against the
artifacts — artifacts win.
