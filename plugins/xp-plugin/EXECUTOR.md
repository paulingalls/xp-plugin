# How you work

Work one story. Card defines scope; Files maps it. Extend Files and report
deviations. Declare each `.xp/` path before editing.

- **Use the reviewed plan.** The lead owns **slate review**. Spawn stages a planner
  and **execution plan review** before multi-file work. Re-read the reviewed plan
  at `{PLAN_PATH}` and route human-only questions to lead.
- **Escalate reserved decisions.** Hand back a wrong card, absent authority or a
  lead-reserved choice. After a mandatory step fails twice for
  infrastructure reasons, commit the coherent in-flight change and hand back.
  File it: `python3 {PLUGIN_ROOT}/scripts/work.py note '...'`.
- **Finish green.** Make small red-green-refactor increments. Run the card's exact
  Verify, commit the green change with hooks enabled and hand back its result.
