---
name: sprint-close
description: Review the sprint's integration, judge it, and release it.
---

# Sprint Close

Every card in the sprint is done or retired before close. Triage open bugs and
debt from `recover`. With `versioning: on`, cut the release artifacts first: the
version in every `version_files` entry and the first CHANGELOG heading. Run the sprint review,
read the review files and the handback it prints; judge what the fix pass left
open: fix, drop with a reason, or debt under both JUDGMENT bars. Unmet ACs and release blockers are not
waivable. Write the retro from the plugin's `templates/retro.md` with the human,
into the sprint's data directory. Land opens the release PR; after it merges, run
post-merge to record the release and, under `versioning: on`, tag the fetched merge
commit with its manifest version. Switch away from the sprint branch so it can be
deleted. An unchanged tree needs no hook rerun and allows a dirty checkout on any
other branch. A changed tree needs a clean checkout on trunk to rerun the sprint hook
detached at the merge SHA, restoring trunk afterward; or supply `--tested-by "<reason>"`
to skip the hook on external evidence. It warns and records `tested_by` in release.json.
`sprint-close` runs in the invoking checkout before tagging and recording the release.
Squash/rebase merges release the fetched trunk tip instead.
After post-merge, check out trunk and update it to the released merge, then run
each milestone's Measure from the repo root and report it to the user.
Rewrite `session.md`.

```
xp.py sprint review <id>
xp.py sprint land <id>
git switch <another-branch>
xp.py sprint post-merge <id>
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
