# Process

`xp.py` is the absolute path in the banner. `--help` lists commands.
Background long legs, no timeout.

**Session start.** Run the banner's `recover`. Disk wins over memory.

**Goals.** A user's goal or complaint about effort becomes a milestone, not
memory. Report progress in its Measure, not card ids. Flat across lands is a
stall: choose continue (say what differs), change tack (delete what did not move
it), or ask; tell the user after. Ask before spending money or altering what
users see.

**Sprint:**
1. `/create-sprint`: write the slate, `xp.py sprint plan <id>`, judge and correct.
2. From trunk, `git switch -c sprint-<id>`, then `xp.py sprint open <id>`.
3. Each story: `xp.py story <id>`, then `/story-close`: judge the review,
   `xp.py story land <id>` onto the sprint branch.
4. `/sprint-close`: `xp.py sprint review <id>`, judge, `xp.py sprint land <id>`;
   after the PR merges, leave the sprint branch, `xp.py sprint post-merge <id>`.

**Story.** Re-run after edits. Delete `plan.md` or
`handback.md` in the story data directory to repeat that stage.

**Free patch.** `xp.py free <slug>` mints a card; fill it, including `Measure:`, run again.
`/free-close`: judge, `xp.py free land <slug>`; after the PR merges,
`xp.py free post-merge <slug>`. Land tears down; the worktree stays until close.

**Post-merge.** Fetch trunk, release its merge SHA. Changed trees rerun proof:
free in its worktree after setup, sprint from clean trunk; or `--tested-by "<reason>"`
skips proof and records evidence. Unchanged trees allow a busy lead checkout.

**Small changes.** Commit through hooks on the sprint branch; outside a sprint,
open a PR to trunk by hand.

**Judgment and records:** JUDGMENT. **Hooks own tests:** Acceptance and `sprint`.
**Close.** Rewrite `session.md`: intent, surprises, tack chosen, next; <30 lines.
