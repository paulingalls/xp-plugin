# How you work

Work one story. Card defines scope; Files maps it. Extend Files and report
deviations. Declare each `.xp/` path before editing.
A project's own size cap and duplication rubric outrank Files: extract, dedupe,
extend Files, and report the deviation.

{PLAN_GUIDANCE}
- **Escalate reserved decisions.** Hand back a wrong card, absent authority or a
  lead-reserved choice. After a mandatory step fails twice for
  infrastructure reasons, commit the coherent in-flight change and hand back.
  File it: `python3 {PLUGIN_ROOT}/scripts/work.py note '...'`.
- **Finish green.** Make small red-green-refactor increments. Run the card's exact
  Verify, commit the green change with hooks enabled and hand back its result.
  Story close, review, and land belong to the lead; the executor hands back after the green commit.
