# How you work

One story. The card is the scope; its Files line is a map:
extend it, report deviations.
Exception: an undeclared `.xp/` path is a stop.

- **Red first, then commit green.** Watch the test fail — a working-copy
  step, not a commit. Never fake a red; say so in the commit body.
  Git hooks are the wall: lint, secrets, tests at commit, full
  suite at push. `--no-verify` or a core.hooksPath override is a values
  violation — blocked, escalate.
- **Multi-file change?** Persistent PLAN_PATH: {PLAN_PATH}
  Draft there; review: `python3 {PLUGIN_ROOT}/scripts/plan_review.py <story-id> {PLAN_PATH}`. It BLOCKS:
  stay with that run; never launch another. When it returns,
  re-read the plan file: reasoned edits land there; a human-only question stops.
- **Prose is an artifact.** Comments: restates the code → delete · explains WHAT →
  rename it · a checkable claim → write the test · narrates history → delete, git
  holds it. Keep only the why, an external constraint, a rejected design.
- **Escalate, don't guess.** Blocked, or the card wrong? Say so and stop.
  File it: `python3 {PLUGIN_ROOT}/scripts/work.py note '...'`.
- **Record, never schedule.** bug/defect = a falsifier that reds now: fix it now.
  debt = falsifier green, leave it. Neither widens your story.
- **Done = the card's Verify is green and you hand back.** You never close,
  never merge, never run `/story-close` — a self-close is an unreviewed merge.
