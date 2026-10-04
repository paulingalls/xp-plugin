---
name: story-close
description: Judge a story's review findings and land it on the sprint branch.
---

# Story Close

`xp.py story <id>` ends by printing the review's findings. Judge every one under
JUDGMENT: fix it with a commit in the story worktree, drop it with a reason, or
file debt under both bars. Unmet ACs and anything the lead reserves are yours,
with the human where needed. Another review after your fixes is optional; land
lists commits after the last review as unreviewed, and the sprint review covers
them. Land, then rewrite `session.md`: intent, surprises, next step, under 30 lines.

```
xp.py story review <id>        # optional, one more review
xp.py story land <id>
xp.py debt --help              # when a finding becomes debt
```
