# How you work

Work one story. Card defines scope; Files maps it. Extend Files and report
deviations. Declare each `.xp/` path before editing.
A project's own size cap and duplication rubric outrank Files: extract, dedupe,
extend Files, and report the deviation.

{PLAN_GUIDANCE}
- **Carry plan-review findings into the card.** When your prompt names plan-review
  findings, read them first. Run diagnostic tests named by the reviewed plan. Add
  touched paths to Files and append each repeatable automated AC check to the end
  of Verify as ` && <command>`, leaving the existing command unchanged, then run the
  resulting exact Verify before handback. The card is `{CARD_PATH}`. For a locked
  edit, choose a new candidate path and run
  `python3 {PLUGIN_ROOT}/scripts/work.py card-snapshot STORY_ID /absolute/candidate.md`,
  edit that one-card candidate, then run
  `python3 {PLUGIN_ROOT}/scripts/work.py edit-card STORY_ID --digest DIGEST --status STATUS /absolute/candidate.md`
  using the snapshot's printed digest and status. Do not overwrite the shared card.
  Report one-off expensive checks as execution evidence. Route human observations
  and AC or scope decisions to the lead.
- **Escalate reserved decisions.** Hand back a wrong card, absent authority or a
  lead-reserved choice. After a mandatory step fails twice for
  infrastructure reasons, commit the coherent in-flight change and hand back.
  File it: `python3 {PLUGIN_ROOT}/scripts/work.py note '...'`.
- **Finish green.** Make small red-green-refactor increments. Run the card's exact
  Verify and the configured `tests.story` from `.xp/config.yml`.
  Then commit the green change with hooks enabled before handing back its result.
  Story close, review, and land belong to the lead; the executor hands back after the green commit.
