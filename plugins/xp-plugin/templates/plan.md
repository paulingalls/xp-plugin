# Plan

<!-- Card status: planned | in-progress | done | retired.
     Files: comma-separated paths the story touches; the executor extends them.
     Acceptance: one command, run from the repo root, that executes the ACs.
     A Gherkin feature is the recommended form: the ACs are its scenarios.
     A sprint or free card may instead use:
     Measure: touches no milestone: <the user's words>
     Optional `Executor: harness/model[/effort]` overrides roles.executor. -->

## Sprint 1 — <title>
Measure: <reading now>; this moves it by <what>, and deletes <what>

#### story-001 — <title>   [planned]
Context: <one paragraph: what this story changes, for whom, and why now>
AC:
- Given a cart with no items, When the shopper adds one item, Then the cart shows 1 item
- Given a cart with one item, When the shopper removes it, Then the cart shows it is empty
Files: src/cart.py, features/cart.feature
Acceptance: <your runner> features/cart.feature

## Free

#### free-<slug> — <title>   [planned]
Context: <what changes, for whom, and why now>
Measure: <reading now>; this moves it by <what>, and deletes <what>
AC:
- Given <state>, When <action>, Then <observable outcome>
Files: <paths>
Acceptance: <one command executing the ACs>
