# Sprint 14 retro — trust the installed copy

Milestone 6 opened with six ordered stories and closes in one sprint. The thesis was
that each harness must be able to trust what the other is running, and that deletion
would fund the proof. It held: the sprint opened at **5,552/5,570 shipped lines** and
closes at **5,566/5,570**. The total cap did not move. Story 077's removal of
`--in-place` funded a zero-sum component re-cut from `spawn` to `hooks` and `misc`;
the six stories spent eight net lines, and round 1's five fixes spent six more.

Release v0.15.0 adds installed-version drift notices, refuses roles whose harness
lacks the plugin before any review spend, offers the normal marketplace install at
setup, gives every free patch the card lifecycle, and states the runner-neutral
working-directory contract for Verify. The last two came from Paul's consumer field
report, not the planned pool. That signal changed the sprint and improved it.

## 1. What the process caught

**Card review falsified the cards before execution.** Story 074 named a test file that
did not exist, and its target test file was already at 499 of the hard 500-line cap.
Both facts were measured and written onto the card before an executor inherited them.
Story 074's plan review then measured a 30–35-line hook cost against an 8-line estimate.
The lead moved only the 30 lines story 077 had already returned, and the executor
stopped when its first green implementation still broke the ratchet. Refactoring, not
a cap raise or weakened guard, made the same behaviour fit.

**Review found boundaries the happy paths concealed.** Across the sprint, reviewers
fixed disabled-role precedence, duplicate install probes, gaps in the free-card
lifecycle, malformed headings, the wrong landing noun, and a shipped-tree neutrality
guard that omitted `unittest`. Story 081's review also replaced a `cd` refusal that
named one test runner with guidance that works for any runner.

**The sprint falsifier batch caught its own bad measurement.** The fast-tier cost
guard went red under unrelated Xcode, simulator, Docker and system load while the
suite's behaviour remained correct. Raw wall clock had made the host part of the
test. A same-run Git fixture now normalizes only slow hosts; a deliberately slowed
suite still reds, and a faster host never tightens the bound. Timer-dependent tests
remain in `full` under the existing `slow` tier instead of pretending to be stable
fast tests.

**The consumer path corrected the lead.** We nearly treated this checkout's
`--plugin-dir` invocation as product policy. Paul's correction made the sprint run the
same marketplace install command a normal consumer needs. That is the path the
release now documents and the path we walked.

## 2. What it missed

**The sprint card still counts itself.** Sprint close refused because `sprint-014`
was planned even though all six ordered stories were done. The lead marked the sprint
card done after checking those stories and the ratchet. This is another instance of
the labelled-line grammar defect already owned by planned story 044; no duplicate
debt was opened.

**Constraint 2 named the timeout failure but not the measurement fix.** It said a
wall-clock guard should be generous or assert the event, yet this repository still
judged a performance budget from raw wall time. The missing rule was same-run control
normalization. The falsifier batch found the contradiction only at sprint close.

**Card file lists repeatedly underdeclared the real change.** Refactoring to stay
under hard file and component caps moved cohesive test helpers into new files, while
review fixes touched adjacent guards. The process caught each tree at review and land,
but the cards remained weak forecasts of the files their acceptance criteria required.

## 3. The rule that earned its place, and what it displaced

Constraint 2 earned an amendment: **normalize raw wall clock against a same-run
control, or use only a generous hang guard and assert the event.** It displaces the
weaker wording that treated generosity as sufficient. The fault-injected unit checks
prove both directions: host slowdown is discounted and suite-only slowdown is not.

Triage earned one operational sentence: **name any tier that still covers a dropped
debt; without coverage, the drop is final.** It makes the cost of archiving explicit
instead of implying that some unnamed future gate will catch the problem. Compressed
concurrency and lane prose pays for it; the system guide is smaller after the change.

## 4. The proposed diff

- **`.xp/constraints.md`** — strengthen constraint 2 with same-run normalization;
  4,495/4,500 characters, still 15/15 constraints.
- **`.xp/system.md`** — add the explicit dropped-debt triage rule while compressing
  concurrency and lane guidance.
- **`tests/scripts/falsifier_fast_tier_cost.py`** — normalize the suite reading with
  the existing same-run Git fixture.
- **`tests/test_fast_tier_falsifier.py`** — fault-inject host-only and suite-only
  slowdown without depending on the host clock.
- **slow-tier classifications** — move watchdog and teardown timing cases out of the
  fast selection while retaining them in the full release wall.

## 5. Carried, and what needs Paul

No open notes and no new debt carry from this sprint. The recurring sprint-card
self-counting defect is scheduled on existing story 044. The remaining planned pool
is stories 069, 040, 044 and 046; Sprint 14 makes no claim about their order.
