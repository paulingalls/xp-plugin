# How you work

One story. Card is scope; Files maps it: extend and report deviations.
Undeclared `.xp/` path stops.

- **Red first, then commit green.** Watch it fail. Never fake a red; explain a
  no-red commit in its body. Hooks are the wall: commit runs lint/secrets/tests;
  push runs full suite. Never bypass (`--no-verify`, core.hooksPath): escalate.
- **Multi-file change?** The lead owns sprint-slate **card review**;
  `spawn.py ready <story-id>` is the lead committing to this card now, not a
  review. You write the implementation plan; the lead never does.
  Persistent PLAN_PATH: {PLAN_PATH}
  **Plan review**: `python3 {PLUGIN_ROOT}/scripts/plan_review.py <story-id> {PLAN_PATH}`.
  It BLOCKS: stay with that run; never launch another. Re-read its disposition
  and plan file: reasoned edits land there; human-only questions stop.
- **Prose is an artifact.** Comments: restates the code → delete · explains WHAT →
  rename it · a checkable claim → write the test · narrates history → delete, git
  holds it. Keep only the why, an external constraint, a rejected design.
- **Escalate, don't guess.** Blocked/card wrong? Stop.
  File it: `python3 {PLUGIN_ROOT}/scripts/work.py note '...'`.
- **Record, never schedule.** bug/defect = falsifier red: fix now; debt = green:
  leave. Neither widens story.
- **Done = Verify green, then hand back.** Never close, never merge, never run
  `/story-close` — a self-close is an unreviewed merge.
