# Process

One page. The values (VALUES.md) cover what this page doesn't.

## The loop

1. **Plan** (any multi-file change): draft the plan, then spawn the **plan-reviewer**
   (fresh context — it owes your plan nothing). Address its findings before writing
   implementation code. It checks TDD ordering, artifact coherence, constraint
   conflicts, and sprint size.
2. **Story**: red → green → refactor, small commits. Git hooks are the wall: lint,
   secrets, fast tests at commit; full tests at push. Never fake a red — a config/docs
   commit says so in its body instead.
3. **Story close**: run the `/story-close` checklist — it spawns the **story-reviewer**
   on the cumulative diff plus anything you filed in work.md, stops for your
   fix-or-ask call, runs the story's Verify commands, records the verdict in the PR
   body, and merges. A conflicted or drifted merge goes back to the reviewer.
   **Review stopping rule** (diminishing returns): one full review always; fixes
   applied exactly as prescribed, with red-first tests, close WITHOUT re-review —
   the prescription was the review. Faithful means SCOPE-IDENTICAL: generalizing
   or "improving" a prescription is a deviation owed re-review (story-002 round 3
   widened a mode-scoped fix to both modes and regressed the guard it fixed).
   When faithfulness is uncertain, one delta ping beats a wrong self-call.
   Re-review is owed for deviations, new uncovered behavior, or conflict
   resolutions. Hard cap two rounds; still contested after that → the human
   decides, not a third round.
4. **Sprint close**: full tier + archived falsifiers batch-run + broad review +
   security review + retro (one-page narrative + a proposed diff to constraints/config
   — a learning that changes nothing executable isn't recorded). Debt triage with the
   human: schedule under budget or drop to archive.

## Records (work.md — via the append CLI once it exists; by hand until then)

- **bug** — claim + falsifier that reds NOW + files. Fix immediately; the red is what
  bounds "now". Can't red? It's not a bug.
- **debt** — claim + falsifier (currently green) + files. Considered only at sprint
  planning: scheduled or dropped to archive. Never scheduled mid-sprint unless it
  blocks the current story's acceptance (which makes it a bug).
- **note** — free text: decisions (choice + because, naming the value tradeoff —
  which value won, which lost), discoveries. Promoted to
  constraints.md at sprint close, or archived.

Telemetry (test/lint failures) is never recorded — the gate re-measures next run.

## Session continuity

`plan.md` story states + git + work.md are the memory. Write the ≤30-line session
digest at story/sprint close only. On start: trust the digest, verify against the
artifacts — artifacts win.
