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
`versioning: on`, tags the fetched merge commit with its manifest version. The lead
checkout may be busy on another branch. A changed merge tree reruns worktree_setup,
then Acceptance detached at the merge SHA in the patch worktree; failure keeps it.
`--tested-by "<reason>"` skips that setup and proof, warns, and records `tested_by`
in landed.jsonl. Squash/rebase merges release the fetched trunk tip instead.
After post-merge, check out trunk and update it to the released merge, then run
each milestone's Measure from the repo root and report it to the user.
Rewrite `session.md`.

Free land runs worktree_teardown but keeps the worktree and branch. Before testing
a review fix made after land, rerun the configured worktree_setup in the patch worktree.
Commit the fix, review it, and land again before merging the PR. Post-merge tears down
again before removal.

Before land, apply or reject each card change proposed in
`<data>/stories/<id>/handback.md`, updating `<data>/plan.md` for accepted changes.

```
xp.py story review free-<slug>   # optional, one more review
xp.py free land <slug>
xp.py free post-merge <slug>
```
