# Process

Every scope runs one cycle: plan, review the plan, do, review the diff, land.

| Scope | Plan | Do | Diff reviewed | Lands on |
|---|---|---|---|---|
| story | one card | executor in a worktree | story branch since fork | sprint branch |
| sprint | the slate | its stories | sprint branch since trunk | trunk, tagged |
| free | one card | executor in a worktree | branch since trunk | trunk, patch tag |

`xp.py` is the absolute path the session banner prints. Every subcommand answers
`--help`; every refusal names the next action. Background long legs, no timeout.

**Session start.** Run the `recover` command the banner prints: `session.md`,
every unfinished card, open records. What is on disk wins over memory.

**Sprint.**
1. `/create-sprint`: write the slate in the plan, then `xp.py sprint plan <id>`.
   A fresh slate reviewer reads the slate. Judge its findings and correct cards.
2. `git switch -c sprint-NNN` from trunk (sprint 7 is `sprint-007`), then
   `xp.py sprint open <id>`.
3. Each story: `xp.py story <id>`, then `/story-close`.
4. `/sprint-close`: `xp.py sprint review <id>`, judge, `xp.py sprint land <id>`;
   after the PR merges, `xp.py sprint post-merge <id>` on trunk.

**Story.** `xp.py story <id>` plans, reviews the plan, executes and reviews the
diff; a card naming one file skips the planner and plan reviewer. It runs only
the stages whose files are missing under the story's data directory: re-run it
after any edit, delete plan.md or plan-review.md to repeat that stage. The
executor runs while `handback.md` is absent or the branch has no commits, and the
reviewer whenever no review recorded the worktree's HEAD, so a crashed review or
a lead commit reruns only the reviewer; delete `handback.md` to execute again.
A `QUESTION:` from the plan reviewer stops the story; answer it in the card,
delete that line from `plan-review.md` (or the file, to re-review), and run
again. `xp.py story review <id>` buys one more review when you want one.
The reviewer sees the card as spawned and as it is now.
`xp.py story land <id>` trial-merges, runs Acceptance on the merged tree, merges
and marks the card done. Commits after the last review land listed as
unreviewed; the sprint review is their net.

**Free patch.** `xp.py free <slug>` mints the card; fill it in and run it again
for a story cut from trunk. `/free-close`:
`xp.py free land <slug>` opens a PR; after it merges,
`xp.py free post-merge <slug>` closes the patch, tagging it under `versioning: on`.

**Judging.** Every finding gets fix, drop with a reason, or debt under both
JUDGMENT bars. Unmet ACs and release blockers are not waivable.

**Records.** `xp.py bug | debt | note | resolve`, per JUDGMENT. Mid-sprint,
record; never schedule.

**Hooks own the tests.** pre-commit and pre-push run the project's tests; the
`sprint` hook runs at sprint land; `nightly` is the project's own. The plugin
runs only a card's Acceptance and the `sprint` hook. Never bypass a hook.

**Close.** At every close, rewrite `session.md` in the data root: intent,
surprises, next step, under 30 lines.
