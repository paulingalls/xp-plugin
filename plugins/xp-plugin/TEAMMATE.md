# How you work

You have one story. The card is the scope; its Files line is a starting map —
extend it and report deviations in your handback.
Exception: an undeclared `.xp/` path is a stop.

- **Red first, then commit green.** Watch the test fail — a working-copy
  step, not a commit. Never fake a red; say so in a config/docs commit
  instead. Git hooks are the wall: lint, secrets, tests at commit, full
  suite at push. `--no-verify` is a values violation — blocked, escalate.
- **Multi-file change?** Draft the plan to a file, then review it headlessly:
  `python3 {PLUGIN_ROOT}/scripts/plan_review.py <story-id> <plan-file>`. Address
  its findings, then write code.
- **Prose is an artifact.** Comments: restates the code → delete · explains WHAT →
  rename it · a checkable claim → write the test · narrates history → delete, git
  holds it. Keep only the why, an external constraint, a rejected design.
- **Escalate, don't guess.** Blocked, or the card is wrong? Say so and stop.
  File it: `python3 {PLUGIN_ROOT}/scripts/work.py note "..."`.
- **Record, never schedule.** bug = a falsifier that reds now, so fix it now.
  debt = falsifier green, leave it. Neither widens your story.
- **Done = the card's Verify is green and you hand back.** You never close,
  never merge, never run `/story-close` — a self-close is an unreviewed merge.
