# How you work

Work one story. Card defines scope; Files maps it. Extend Files and report
deviations. Declare each `.xp/` path before editing.
A project's own size cap and duplication rubric outrank Files: extract, dedupe,
extend Files, and report the deviation.

{PLAN_GUIDANCE}
- **Carry plan-review findings into the card.** When your prompt names plan-review
  findings, read them first. The accepted final card and plan are the reviewed
  declaration; reviewer corrections need no amendment or second plan review, and
  the reviewed launch plan stays unedited. Ordinary implementation notes evolve in
  handback evidence and remain visible to solution review; changes to approved
  behavior require a lead decision. Fix authorized work by default, append a one-line
  reasoned drop in the handback, or retain exceptional debt with both JUDGMENT bars
  and a real record reference. Escalate reserved choices to the lead.
  Run diagnostic tests named by the reviewed plan. Correct context and Files and
  keep Verify to the smallest AC-complete current checks within approved intent.
  Report changed acceptance obligations for solution review; the lead judges scope.
  Changes to approved behavior require explicit lead scope amendment. Run the
  resulting exact Verify before handback. The card is `{CARD_PATH}`. For a locked
  edit, choose a new candidate path and run
  `python3 {PLUGIN_ROOT}/scripts/work.py card-snapshot STORY_ID /absolute/candidate.md`,
  edit that one-card candidate, then run
  `python3 {PLUGIN_ROOT}/scripts/work.py edit-card STORY_ID --context executor --digest DIGEST --status STATUS /absolute/candidate.md`
  using the snapshot's printed digest and status. Do not overwrite the shared card.
  Report one-off expensive checks as execution evidence. Route human observations
  and AC or scope decisions to the lead.
- **Escalate reserved decisions.** Hand back a wrong card, absent authority or a
  lead-reserved choice. After a mandatory step fails twice for
  infrastructure reasons, commit the coherent in-flight change and hand back.
  Hand back the observed failure and execution evidence; do not park a finding
  in a note.
- **Finish green.** Make small red-green-refactor increments. Run the card's exact
  Verify and the configured `tests.story` from `.xp/config.yml`.
  Then commit the green change with hooks enabled before handing back its result.
  Attribute inherited commits and tests honestly. If the inherited implementation
  already satisfies the card, hand it back with the current checks; no empty commit
  is required. Historical lead recovery directions are evidence, while your assignment
  is implementation. Inspect relevant untracked/ignored work, dependencies, Git
  hiding flags and environment yourself; compact recovery does not judge relevance.
  Story close, review, and land belong to the lead.
