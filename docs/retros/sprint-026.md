# Sprint 26 retro — "A dead attempt is not live work, a repaired Verify is not a new review"

Three cards, three GitHub issues, one card each at Paul's pick: 144 (#122, an abandoned slate
review is retired at open and recovery tells running, incomplete and released apart), 145 (#118,
`repair` records a red-Verify round after a bounded lead repair), 146 (#124, `open_sprint.py`).
Three lanes ran in parallel; each closed in ONE review round with no blocking findings and zero
lead fixes. Milestone 14 closes here, at v0.27.0.

## 1. What the process CAUGHT that we would otherwise have shipped

**Slate review caught what reading the code could not.** Round 1 constructed three traps:
- Retiring a slate marker promotes a killed round's fragment into a counted round.
- `reviewed_head=verify_head` would have disclosed the lead's repair as the reviewer's work.
- `cmd_start` falls into the close batch on a first open when every card is done.

Round 2 caught two more:
- A `--cancel` that signals the runner orphans the agent, which runs in its own session.
- Tests execute the stored `next` path the card meant to rewrite.

Every one of these would have shipped a corrupted record or a false guarantee.

**Story reviewers each fixed a real defect inside their round.** Each fix was fault-injected
against the old code.
- 146: `/create-sprint` named a script with no exec bit. The route walk always launches with
  `python3`, so it could not see that. It now asserts a path-first command is runnable.
- 145: an empty commit was accepted as a "repair" of a flaky Verify.
- 144: recovery reported another user's process as our running review.

## 2. What it MISSED, and which mechanism should have caught it

**The map pass answered "where is the code", not "what else depends on it".** Mapping cut
falsified premises to one (the banner text). But slate review still returned 25 findings over
two rounds, nearly all omitted consumers:
- tests that execute or assert the artifact the card changes;
- a second writer of the same marker;
- the process tree a signal must reach;
- the settled DESIGN rule a new path contradicts.

The mapping prompt is ours (memory, not shipped). It now asks for consumers as well as locations.

**The cap made the lead cut, not fix.** Round 2 ended the reviews with two guarantees unworkable
as written. The lead cut them (`--cancel`, the path rewrite) and Paul approved. That is the cap
working. But #122 now ships only part of its fix: a slate review that dies after the sprint opens
still reads incomplete. The #122 reply says so.

## 3. Which rule earned its place, and which cost more than it returned

**EARNED: no lead fixes at close (Paul, Sprint 24), for the second sprint running.** Three
cards, three rounds, zero confirming rounds.

**EARNED: the two-round slate cap.** It forced the scope decisions to Paul at open, where they
cost a question, instead of into a third round.

**COST MORE THAN IT RETURNED: nothing new.** Card refresh changed citations only, on all three
cards. It was cheap, and it confirmed the slate was current.

## 4. The proposed diff

None to constraints, config or shipped prose. `repair`'s exception to the stopping rule landed
in DESIGN.md and both close skills with story-145 (Paul approved it at open). Records: 11 notes
triaged (1 promoted, 10 dropped, and the #122 remainder carried to its GitHub reply). All 78
resolved records kept (`2b5a456d`, 141s, is still the fast-tier cost guard).
