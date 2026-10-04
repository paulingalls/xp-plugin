# Plan

<!-- Card status: planned | in-progress | done | retired.
     Files: comma-separated paths the story touches; the executor extends them.
     Acceptance: one command, run from the repo root, that executes the ACs.
     A Gherkin feature is the recommended form: the ACs are its scenarios.
     Optional `Executor: harness/model[/effort]` overrides roles.executor. -->

## Milestone 1 — <title>
Done when: <the observable outcome that ends the milestone>

## Sprint 1 — <title>

#### story-001 — <title>   [planned]
Context: <one paragraph: what this story changes, for whom, and why now>
AC:
- Given a cart with no items, When the shopper adds one item, Then the cart shows 1 item
- Given a cart with one item, When the shopper removes it, Then the cart shows it is empty
Files: src/cart.py, features/cart.feature
Acceptance: <your runner> features/cart.feature
