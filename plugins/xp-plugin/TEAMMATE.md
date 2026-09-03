# How you work

One story. Card is scope; Files maps it: extend and report deviations.
Undeclared `.xp/` path stops.

- **Multi-file change?** The lead owns **slate review**; the lead never writes
  the implementation plan. Spawn runs it and its **execution plan review** as
  stages before you, so start no review yourself — nothing you launch outlives
  your turn. Re-read the reviewed plan file: reasoned edits land there, and
  human-only questions stop the run before it reaches you.
  Persistent PLAN_PATH: {PLAN_PATH}
- **Escalate, don't guess.** Blocked/card wrong/a decision reserved to the lead?
  Stop. If a mandatory step fails twice for infrastructure reasons, stop rather
  than proceed. Commit a coherent in-flight change or discard only your own edits;
  then file it and hand back.
  File it: `python3 {PLUGIN_ROOT}/scripts/work.py note '...'`.
- **Done = Verify green, work COMMITTED, then hand back.** Small commits. Never
  close, never merge, never run
  `/story-close` — a self-close is an unreviewed merge.
