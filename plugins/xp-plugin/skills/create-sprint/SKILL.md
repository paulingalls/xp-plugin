---
name: create-sprint
description: Author a sprint slate before story slots are spent.
---

# Create Sprint

`templates/plan.md` owns card shape; setup already copied it to the per-clone
plan path `/xp-setup` prints.

Before writing:

- Budget story slots against `sprint_cap`; `debt_budget` bounds the share spent
  on scheduled debt.
- Put prerequisites first in merge order. Find file collisions between cards;
  order or split them before execution.
- Write each `Verify:` as argv executed from the repo root: unquoted `&&` may
  chain commands; every other shell metacharacter is refused, as are `cd` and an
  argv[0] absent from PATH.

## Open

When the slate is complete, give a fresh `slate-reviewer` the full proposed slate,
`sprint_cap`, VALUES, JUDGMENT, constraints and system context; do not give it the
author's conclusions. Check EVERY per-card and slate result from
`slate_review.py <id>`, record accepted and rejected conclusions with `work.py note`,
leaving corrected cards only. Then `git switch -c sprint-<id:03d>` and
`close.py sprint <id> start`; unfinished output says close checks wait.

## Done

Do not run `spawn.py ready <story-id>` for any card until the review and sprint
open are complete.
