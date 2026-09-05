# Sprint 19 retro — preserve the evidence, then act on it

Six cards landed in dependency order. The full tier closed at 1,315 passing
tests, up from the 1,237-test baseline named by the opening extraction card. The
sprint changed review evidence, role routing and release refusal paths without
relaxing the 500-line file wall.

## 1. What the process caught

**Slate review corrected premises before slots were spent.** It found that the
durable-review card's debt premise was already false, made structural extraction
a separate prerequisite, and turned five overlapping behavior cards into an
explicit serial lane. That kept cap work out of the later deep-review diffs.

**Execution-plan review made the release claims executable.** It required the
combined falsifier to rerun every distinct red command, preserved the existing
boolean API, and named the archive as the source of compacted Files evidence.

**Diff review found holes that green focused suites missed.** The story-108
reviewer constructed a second record sharing one red command and exposed both
uncovered source attribution and append-only filing. It also fault-injected the
missing-Files refusal. The patch added those cases before merge.

**Sprint start exercised every remaining record before the full tier.** The
falsifier batch and 1,315-test full run were green on the assembled sprint, not
in six isolated worktrees.

## 2. What it missed

**The cap named extraction as an action but left its authority implicit.** An
executor stopped at a test-file boundary even though extraction was the only
compliant response. The human had to state the intended rule: extraction never
needs a separate approval, and its invariant is the same collected passing-test
count before and after. The retro makes that existing obligation explicit in
both the dogfood and scaffolded constraints.

**Reviews produced several useful but not yet executable observations.** They
included a possible double-fetch race, review-artifact allocation concurrency,
late role preflight, role-grammar disagreement and evidence-bundle growth. None
has a constructed falsifier establishing a card-sized defect. This close drops
them explicitly; existing constraints still require a future rediscovery to be
checked before it is promoted.

**One corrected note survived beside its mistaken predecessor.** Both are
archived in one triage: the correction supplies the accurate shell-wrapper
mechanism, while the predecessor remains historical rather than authoritative.

## 3. Which rule earned its place, and which cost more than it returned

**Earned: fault-inject every guard.** It found the shared-command and append-only
holes only after the implementation and focused tests were green.

**Cost: the implicit permission boundary in the file-cap rule.** “Over-cap means
extract” specified the operation but not that an executor may perform it without
asking, so it caused a stop without protecting behavior. This is a correction to
constraint 8, not a sixteenth obligation; no rule is displaced.

## 4. The proposed diff

1. **`.xp/constraints.md`, item 8:** replace the implicit “over-cap means
   extract” instruction with explicit standing authority and a before/after
   collection-and-green invariant.
2. **`plugins/xp-plugin/templates/constraints.md`, item 2:** ship the same
   correction to consuming projects.
3. **No new cards or constraints:** archive all 27 notes with a disposition;
   completed review decisions, accepted loud tradeoffs and unfalsified risks do
   not carry merely because they were noticed.
