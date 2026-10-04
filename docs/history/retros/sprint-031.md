# Sprint 31 retro — the finding reaches the executor, and recovery runs as printed

Two serial stories landed in one review round each. Story 161 repairs the gap between
plan review and the first executor. Story 162 keeps SessionStart recovery executable
when the plugin cache moves. Both surfaces were walked in scratch consuming projects
on Codex and Claude Code. Sprint start's falsifier batch was green.

## 1. What the process caught

The story 161 review caught a missing-findings refusal that told the lead to resume,
although resume would repeat the same refusal. It also replaced a later-round test
that did not construct the stale-round condition. The story 162 review made the
missing-pinned-root test actually pin a missing root; before that fix, the test
passed against the original broken recovery command. These were review findings
about behavior and test power, not formatting.

The consuming walks caught what unit tests alone could not establish: the
first executor prompt made the findings and locked card-edit route usable in
both harnesses, and each installed SessionStart command ran from its own project.
Codex retained the final project-data fence. The long-root profile delivered
every numbered constraint at 9,295 of 9,500 bytes.

## 2. What it missed

The earlier consumer stories exposed the plan-to-executor gap: plan review found
repeatable tests and files absent from the card, but its findings were left in a
separate disposition and the first executor prompt had already been built. The
plan handoff now carries the current findings, and the executor has a locked
additive card-edit route. The reported project-specific prebuild and phone-call
checks remain execution evidence, not recurring Verify commands.

The reviewer also noted a misleading resume dry-run preview, a conflict between
`.xp/` path guidance and card-growth refusal, and a stale slow-test node id from
the preceding free patch. The stale id and preview are pool cards 163 and 164
for a future slate. The `.xp/` collision is a loud close refusal; this sprint
did not establish a silent failure or a safe widening of card growth.

## 3. Rules and cost

Constraint 12 earned its place: walking the consuming path established both
the executor's use of external findings and the installed recovery command.
Constraint 8's 500-line cap cost extraction in both stories, but the extracted
banner and prompt code kept the files below the cap and made the behavior easier
to review. No rule displacement is justified by these results. The full tier ran
at each land (1,598 and 1,602 passing tests respectively), and the sprint-start
falsifier batch took 135 seconds across 78 resolved records. The recurring cost
is visible; this sprint did not establish a safe cut to that coverage.

## 4. Proposed diff

No new constraint or charter rule. The executable changes are the two landed
stories and the v0.32.0 release entry. Ten notes were triaged and compacted:
two promoted to the Milestone 20 pool, two superseded by this sprint's work,
and six archived as decision, walk or loud-residue records. The 78 resolved
falsifiers stay active; archiving them would forfeit recurring checks to save
135 seconds in this close, without evidence that their guarantees are replaced.
