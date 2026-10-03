## bug 2026-09-08T17:56:12Z
Claim: close.py sprint <id> milestone-done --dry-run PERFORMS THE CLOSE. The sprint subparser accepts --dry-run for every action, but close.py:453 calls sprint_close.milestone.cmd_done(a.sprint_id) with no dry_run argument, so the flag is parsed and dropped. cmd_done then runs the Done when: commands and flips [in-progress] to [done] exactly as the real leg does — measured: --dry-run and no flag are byte-identical in effect, both rc=0, both printing 'milestone done:'. MEASURED LIVE THIS SESSION: I ran the flag as a preview against Sprint 21 and it closed Milestone 11; the real run that followed correctly refused as already-done, and only the plan.md mtime showed which invocation had done the work. review and land honour the flag, so a lead has every reason to believe this action does too. Distinct states — preview and perform — are not distinct here (constraint 15), and the surface is prose an agent is told to run (constraint 12).
Id: b5cfb5e9
Resolves: b5cfb5e9
Disposition: resolved
Falsifier: `pytest -q tests/test_milestone.py::test_milestone_done_dry_run_runs_the_condition_without_changing_plan`
Covered by: fast
Files: plugins/xp-plugin/scripts/close.py,plugins/xp-plugin/scripts/close/milestone.py,tests/scripts/falsifier_milestone_done_dry_run.py

## note 2026-09-08T18:34:32Z
