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
post-merge on trunk to tag and record the release. Rewrite `session.md`.

```
xp.py sprint review <id>
xp.py sprint land <id>
git switch <trunk> && git pull
xp.py sprint post-merge <id>
```
