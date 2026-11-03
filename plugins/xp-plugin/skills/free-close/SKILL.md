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

The walk can stop (exit 3) on a `QUESTION:` line in
`<data>/stories/<id>/handback.md`. Clear the block, then delete handback.md to
re-run the executor when the work is unfinished; or delete the QUESTION line to
review only when the committed part should be judged as it stands.
For review findings, fix with commits in the worktree, then land; commits after
the review are listed as unreviewed, and another review is optional. Delete
handback.md to re-run the executor only for a finding needing a fresh implementation.

Before land, apply or reject each card change proposed in
`<data>/stories/<id>/handback.md`, updating `<data>/plan.md` for accepted changes.

```
xp.py story review free-<slug>   # optional, one more review
xp.py free land <slug>
xp.py free post-merge <slug>
```

With `versioning: notes`, add `changes/<actual-git-branch>.md` before land, with
exactly one required `Bump: major|minor|patch` line, a user-facing body and a required
`Release steps:` line (`none.` or a list). Leave CHANGELOG.md and configured manifest
versions unchanged. Post-merge tags nothing and nudges to `xp.py release stamp`.
Run that command on clean trunk equal to origin after fetch. It consumes pending
notes in adding order, uses their highest Bump against the latest origin vX.Y.Z tag,
writes manifests and one CHANGELOG section, and creates the release commit and
annotated tag. The stamp pushes directly to trunk, atomically with the tag; a
protected trunk needs a bypass for that push. Publication is CHANGELOG only;
Release steps remain generic text. With `versioning: off`, the project owns versions
and tags.
