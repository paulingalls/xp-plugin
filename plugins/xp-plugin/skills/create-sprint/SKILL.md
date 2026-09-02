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

When the slate is complete, run `/sprint-close` for independent slate review and
correction; it owns the reviewer mechanics. Do not run
`spawn.py ready <story-id>` for any card until that review is complete.
