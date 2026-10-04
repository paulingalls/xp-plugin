# Process

`xp.py` is the absolute path the session banner prints. Subcommands answer
`--help`. Background long legs, no timeout.

**Session start.** Run the banner's `recover` command. Disk wins over memory.

**Sprint**, in order; skills hold the details:
1. `/create-sprint`: write the slate, `xp.py sprint plan <id>`, judge the slate
   review and correct cards.
2. From trunk, `git switch -c sprint-<NNN>` (7 is `sprint-007`), then
   `xp.py sprint open <id>`.
3. Each story: `xp.py story <id>`, then `/story-close`: judge the review,
   `xp.py story land <id>` onto the sprint branch.
4. `/sprint-close`: `xp.py sprint review <id>`, judge remaining findings,
   `xp.py sprint land <id>`; after the PR merges, on updated trunk,
   `xp.py sprint post-merge <id>`.

**Story.** Re-run after edits; follow the printed next step. Delete `plan.md`
or `handback.md` in the story's data directory to repeat that stage.

**Free patch.** `xp.py free <slug>` mints the card; fill it in, run it again
for a story from trunk. `/free-close`: judge the review, `xp.py free land <slug>`;
after the PR merges, on updated trunk, `xp.py free post-merge <slug>`.

**Small changes.** Too small for a card: commit through hooks on the sprint
branch; outside a sprint, open a PR against trunk by hand.

**Judging and records** follow JUDGMENT. **Hooks own the tests**: the plugin
runs only a card's Acceptance and the `sprint` hook.

**Close.** At every close, rewrite `session.md` in the data root: intent,
surprises, next step, under 30 lines.
