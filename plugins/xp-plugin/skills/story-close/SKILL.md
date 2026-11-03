---
name: story-close
description: Judge a story's review findings and land it on the sprint branch.
---

# Story Close

`xp.py story <id>` ends by printing the review's findings. Judge every one under
JUDGMENT: fix it with a commit in the story worktree, drop it with a reason, or
file debt under both bars. The reviewer may have committed fixes: read those
commits as you read the findings; they are yours to accept, change or revert in
the story worktree. Unmet ACs and anything the lead reserves are yours,
with the human where needed. Another review after your fixes is optional; land
lists commits after the last review as unreviewed, and the sprint review covers
them. Land, then rewrite `session.md`: intent, surprises, tack chosen, next step, under 30 lines.

The walk can stop (exit 3) on a `QUESTION:` line in
`<data>/stories/<id>/handback.md`. Clear the block, then delete handback.md to
re-run the executor when the work is unfinished; or delete the QUESTION line to
review only when the committed part should be judged as it stands.
Delete handback.md to re-run the executor only for a finding needing a fresh implementation.

Before land, apply or reject each card change proposed in
`<data>/stories/<id>/handback.md`, updating `<data>/plan.md` for accepted changes.

```
xp.py story review <id>        # optional, one more review
xp.py story land <id>
xp.py debt --help              # when a finding becomes debt
```
