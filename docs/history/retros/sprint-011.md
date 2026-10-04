# Sprint 11 retro — projects act, milestones move

Two deferred product decisions landed. Story 065 gives a project one shell-free
lifecycle command at sprint-open, story-close and sprint-close. Story 064 makes the
pipeline own milestone brackets while the lead retains completion judgment. The
release is v0.12.0.

## 1. What the process caught

**Plan review tested the model against the live plan before code.** The first Story
064 plan counted every structurally nested card. Nine planned cards in explicitly
unscheduled pool sections would therefore suppress milestone completion forever.
Review stopped, the lead defined membership as cards under `### Sprint ...` sections,
and a second pass required fixtures that construct the unscheduled case.

**Story review fault-injected the boundaries, not just the happy path.** Story 065's
review found that macOS `/usr/bin/cd` could make a chained Verify run from the wrong
directory, and that a lifecycle `&&` mutation silently ran only half the command.
Story 064's review found sprint-open compatibility regressions, a vacuous status
guard that would re-propose completed milestones forever, and collapsed refusal
states. Each finding landed with a test that reds on the demonstrated mutation.

**The durable falsifier batch stopped the release twice.** A resolved status-flip
record still called the old API; its exact replacement node now covers all three
transitions. The 120-second fast-tier guard then materialised at 125.0s/967 tests.
Keeping all thirteen cases while reusing three repository fixtures brought the same
guard to 101.1s/957 tests and 106ms/test; neither bound moved.

## 2. What it missed

**Budget pressure erased seven measured guard rationales.** Story 064 stayed under
the close cap by deleting local why-comments unrelated to its feature. Review named
the loss but could not restore seven lines inside a component with one free. Story
070 makes the zero-sum allocation a planning decision instead of another deletion
made under implementation pressure.

**Milestone assent can outlive a changed declaration.** The action rechecks scheduled
cards after `Done when:` runs, but not the declaration itself. A concurrent edit can
replace the condition before the `[done]` flip. Story 069 carries the exact stale-
declaration refusal; this sprint does not mark the live Milestone 4 done because its
current `Done when:` is prose.

## 3. What earned its place, and what cost more than it returned

**Earned: constructed fault injection and exact durable falsifiers.** The membership
fixture had to contain an open unscheduled card; the semicolon case had to succeed if
the parser guard vanished; the empty-member test had to invoke the explicit action.
Exact records then caught an API migration and a materialised performance debt.

**Cost more than it returned: one fresh git repository per parameter value.** The
cases were independent assertions but not independent repository histories. Reusing
one fixture per group preserved every state and refusal check while removing ten
pytest items and repeated git setup. This is a test-design correction, not a weaker
fast-tier threshold.

## 4. The proposed diff

- **`docs/DESIGN.md`: state the shipped validation boundary.** Plan review requires
  runnable `Verify:`; explicit milestone completion validates `Done when:`.
- **Milestone tests:** construct empty membership and shell-syntax mutations, while
  reusing repositories across parameter cases to keep the commit wall usable.
- **Plan cards 069–070:** refuse stale `Done when:` assent; restore guard rationale
  under a planning-time zero-sum allocation.
- **No constraint or system rule added.** Constraints 2, 11, 13 and 15 already made
  every close decision; more prose would duplicate rules that worked.

## 5. What carries

Nothing remains only in the note ledger. Stories 069 and 070 are explicit,
unscheduled cards. The remaining observations were archived as shipped, bounded or
dropped with reasons.
