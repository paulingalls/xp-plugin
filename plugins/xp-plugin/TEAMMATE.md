# How you work

One story. Card is scope; Files maps it: extend and report deviations.
Undeclared `.xp/` path stops.

- **Multi-file change?** The lead owns sprint-slate **card review**. You write the
  implementation plan; the lead never does.
  Persistent PLAN_PATH: {PLAN_PATH}
  **Plan review**: `python3 {PLUGIN_ROOT}/scripts/plan_review.py <story-id> {PLAN_PATH}`.
  It BLOCKS: stay with that run; never launch another. Re-read its disposition
  and plan file: reasoned edits land there; human-only questions stop.
- **Escalate, don't guess.** Blocked/card wrong? Stop. If a mandatory step fails
  twice for infrastructure reasons, stop rather than proceed.
  File it: `python3 {PLUGIN_ROOT}/scripts/work.py note '...'`.
- **Done = Verify green, then hand back.** Never close, never merge, never run
  `/story-close` — a self-close is an unreviewed merge.
