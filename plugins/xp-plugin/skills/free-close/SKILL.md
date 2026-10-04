---
name: free-close
description: Judge a free patch's review findings and release it from trunk.
---

# Free Close

`xp.py free <slug>` ends by printing the review's findings. Judge every one under
JUDGMENT: fix it with a commit in the patch worktree, drop it with a reason, or
file debt under both bars. Cut the release artifacts before land: the patch
version in every `version_files` entry and the first CHANGELOG heading. Land
opens the PR against trunk; after it merges, post-merge tags the patch. Rewrite
`session.md`.

```
xp.py story review free-<slug>   # optional, one more review
xp.py free land <slug>
xp.py free post-merge <slug>
```
