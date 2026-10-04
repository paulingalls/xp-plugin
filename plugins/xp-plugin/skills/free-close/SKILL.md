---
name: free-close
description: Judge a free patch's review findings and release it from trunk.
---

# Free Close

`xp.py free <slug>` mints the card on its first run and, once the card is filled in,
ends its second run by printing the review's findings. Judge every one under
JUDGMENT: fix it with a commit in the patch worktree, drop it with a reason, or
file debt under both bars. With `versioning: on`, cut the release artifacts before
land: the patch version in every `version_files` entry and the first CHANGELOG heading. Land
opens the PR against trunk; after it merges, post-merge closes the patch and, under
`versioning: on`, tags it. Rewrite `session.md`.

```
xp.py story review free-<slug>   # optional, one more review
xp.py free land <slug>
xp.py free post-merge <slug>
```
