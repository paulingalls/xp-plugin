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
`xp.py recover` and report each milestone's measure to the user.
Rewrite `session.md`.

```
xp.py sprint review <id>
xp.py sprint land <id>
git switch <another-branch>
xp.py sprint post-merge <id>
```
