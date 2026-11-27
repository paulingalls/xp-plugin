# Process

`xp.py` means the banner path. Commands: `--help`.
Background long legs via the harness, no timeout or `&`; write/read a file, never pipe/filter.

**Session start.** Run banner `recover`. Disk wins over memory.

**Goals.** Record goals and effort complaints as milestones. Report their Measures,
not card ids. Flat across lands: continue (say what differs), change tack (delete
what did not move it), or ask; tell the user. Ask before spending money or
altering what users see.

**Sprint:**
1. `/create-sprint`: write the slate, `xp.py sprint plan <id>`, judge and correct.
2. From trunk, `git switch -c sprint-<id>`, then `xp.py sprint open <id>`.
3. Each story: `xp.py story <id>`, follow its `next:` lines, `xp.py story land <id>`.
4. `/sprint-close`: `xp.py sprint review <id>`, judge, `xp.py sprint land <id>`;
   after the PR merges, leave the sprint branch, `xp.py sprint post-merge <id>`.
   Retry retro: `xp.py retro <id>`; repair any failed issue receipt first.

With `github_issues: on`: `xp.py card publish <id>`, `xp.py card claim <N>`.
Planned non-slate cards move onto issues after publisher Context, scan and create
succeed; failures preserve the plan. Claim in any clone imports Context; sync
preserves it. Slates retain Issue pointers/private Context, publishing a clone
placeholder. Republish skips publisher. The lead checks personal material;
gitleaks checks secrets only. Retro files unfiled proposals; closed issues supply
dispositions.

**Story.** Re-run after edits. Delete story data's `plan.md` or `handback.md`
to repeat that stage.

**Free patch.** `xp.py free <slug>` mints a card; fill it with `Measure:`, rerun.
Follow `next:`, `xp.py free land <slug>`; after merge, `xp.py free post-merge <slug>`.
Land tears down; the worktree stays until close.

**Post-merge.** Fetch trunk; release its merge SHA. Changed trees rerun proof:
free in its worktree after setup, sprint from clean trunk; `--tested-by "<reason>"` instead
records evidence. Unchanged trees allow a busy lead checkout.

**Small changes.** Commit through hooks on the sprint branch; outside a sprint,
open a PR to trunk by hand.

**Judgment and records:** JUDGMENT. **Hooks own tests:** Acceptance and `sprint`.
**Close.** Rewrite `session.md`: intent, surprises, tack chosen, next; <30 lines.
