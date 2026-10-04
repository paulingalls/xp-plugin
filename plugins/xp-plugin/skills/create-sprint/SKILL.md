---
name: create-sprint
description: Write a sprint slate, have it reviewed, and open the sprint.
---

# Create Sprint

Write the sprint's cards in the plan file `recover` names, in the shape the
plugin's `templates/plan.md` shows. Carry unfinished cards forward first. Each
card's Acceptance is one command, run from the repository root, that executes its
ACs; a Gherkin feature run by the project's runner is the recommended form.
A sprint is one release: self-contained and releasable on its own, whether that
is three cards or eight; `debt_budget` caps the share of debt. Order
prerequisites first and split cards that collide on files. Then run the slate
review, judge every finding in the slate review file it names (correct the card,
drop with a reason, or file debt under both JUDGMENT bars), answer each
`QUESTION:` with the human, and open the sprint. Addressed findings need no
second review.

```
xp.py sprint plan <id>
git switch -c sprint-<id>      # from trunk; sprint 7 is sprint-007
xp.py sprint open <id>
```
