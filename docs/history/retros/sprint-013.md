# Sprint 13 retro — every mechanism has a reader, or it goes

Milestone 5 opened and completed in one sprint: 6 stories — 5 scheduled cards plus a
mid-sprint addition from a field report. Release v0.14.0. Three cards RETURNED shipped
lines (-19, -41, -24) and three SPENT (+7 the archived-record fix, +17 github issue
#38's parser, +17 the amend verb), measured at each merge commit.

The milestone's thesis was that we ship mechanisms nothing reads, and that removing
them would fund the sprint's own spending. It held, and the number is the whole
argument: the six cards returned **43 lines** — 5,569/5,570 at open, **5,526 at the
release commit a48bb2d** — while adding an amend verb, a fenced-disposition parser
and an archived-record exclusion. **No cap was raised and no sub-budget re-cut,
across six cards.** The single free line at open was never spent.

EVERY FIGURE HERE IS ANCHORED TO A COMMIT, and that is a lesson this retro learned
about itself rather than a formatting choice. The first draft cached "43 at close";
sprint review round 1 blocked on it, because its OWN fixer had just spent 24 of those
lines in `misc` buying a guard that refuses resolving an ARCHIVED record — the
read-time half of the boundary story-051 left open. The correction then went stale
again two lines' worth when round 2 patched the fence spelling. **A prose number
about the tree is invalidated by the very round that verifies it**, so a close figure
quoted flat is wrong by construction. Run `tests/scripts/ratchet.py` — the live table
is the only authority, which is what CLAUDE.md already says and what this paragraph
now stops contradicting. What the rounds bought is worth their lines both times.

## 1. What the process caught

**Three cards shipped a vacuous test, and mutation found all three — reading found
none.** Story 072's replacement test asserted absence over an EMPTY data root, where
the function it guarded returns `"none"` regardless, so only a literal section title
could ever have redded; a project upgrading from v0.13.0 still has the store on disk,
which is the one case that mattered. Story 051's three exclusion tests all passed
against `batch = []` — an exclusion asserted as "this counter did not grow" certifies
a do-nothing close, in the one direction its own card said must never move by
accident. Story 073's three liveness tests passed against a hook that never ran at
all. Each was found by a reviewer mutating the mechanism, never by reading the diff.

**Reviewers falsified two card premises by running the code.** Story 051's card
framed the archived-falsifier gap as an oversight; `DESIGN.md` specified the opposite
behaviour in four places, with reasoning. Story 073's card cut `debt_budget` claiming
it "NAGS EVERY CONSUMING PROJECT AT EVERY SESSION START" — the reviewer scaffolded a
fresh repo, measured `config_age()` returning `''`, found the key has the same reader
`sprint_cap` was kept for, and restored it. A consuming project would otherwise have
reached sprint close and been told to schedule debt under a budget existing nowhere.

**Story 068's review disproved its own card's central claim.** The card argued the
amend verb "replaces a worse path that is already open". The reviewer built the
hatch: `spawn --in-place` flips `[ready]→[in-progress]` without writing the handoff
marker the new mint guard keys off, so re-minting succeeded with `amendments` absent
and land would have accepted text no reviewer saw. One line closed it.

**The falsifier batch caught a cross-file regression one card later.** Story 075 added
a pre-push stanza; bug a8195145's falsifier replays the whole wall in a temp fixture,
its control refused to read a fixture failure as proof of the wall, named the broken
stanza, and aborted the sprint close. That control exists because the falsifier once
passed vacuously on a missing ratchet. It paid for itself here.

## 2. What it missed

**Cards were written with premises nobody had checked, and promotion is where it
happens.** Note 8d662bf4 measured seven launderings at Milestone-5 planning; this
sprint added two more. The mechanism is specific and constraint 13 did not cover it:
a note is provisional and triage disposes of it in minutes, but PROMOTING it onto a
card converts it into a directive an executor inherits as fact, and nothing between
those two states re-checks it. **This is the sprint's promoted rule.**

**Two cards' `Verify` lines did not execute their own ACs.** Story 072's AC3 named
three refusals whose tests live in three files Verify never ran; story 073's new
assertions landed in six such files. Both were caught by plan review and covered by
the story tier at land, so nothing shipped unproven — but the card's own contract was
wrong twice, which is a pattern rather than a slip.

**A wall-clock bound measured the machine, again.** `test_a_hung_teardown...` missed a
20s bound by 0.06s under xdist load and red the sprint's last land. Its own comment
recorded being tuned 5 → 20 for the same reason. Constraint 2 already names the rule —
generous, or assert the event — and the event assertion was present but ordered last.

**Hand-editing work.md moved a record's identity.** Repairing a note the shell had
mangled changed its bytes, and ids are `sha256(entry)`: `03716639` became `66bee349`,
orphaning every cross-reference written before the repair.

## 3. The rule that earned its place, and what it displaced

Constraint 2 earned it outright: it found three vacuous tests and one miscalibrated
timeout this sprint, none of which reading caught.

Constraint 13 earned an EXTENSION rather than a new rule, and pays for itself: it
already forbids writing an unchecked claim, so covering the promotion site costs 8
characters instead of a 16th line-item. Nothing is retired — an amendment displaces
nothing, which is the cheapest promotion available and the reason to prefer it.

What cost more than it returned: nothing was retired this sprint. `constraints_cap`
went from `.xp/config.yml` because story-073 stopped shipping it and it had no reader,
taking a one-key allowlist in `tests/test_dogfood.py` with it.

## 4. The proposed diff

- **`.xp/constraints.md:49-51`** — constraint 13, "A card, a plan or a review that
  asserts what the code does" → "A card, plan, review or PROMOTED note asserting what
  the code does". 4487 → 4495 of 4500 characters; still 15/15 line-items.
- **`docs/DESIGN.md:240-246`** — delete the `tests:` yaml block, a second copy of
  `templates/config.yml` whose comments had already drifted from it at v0.13.0.
  Replaced by a sentence naming the template as the single copy, the same resolution
  CLAUDE.md applies to tiers.
- **`.xp/config.yml:6`** — remove `constraints_cap: 15`; nothing reads it and the
  seed `constraints.md` already states the cap in its own header.
- **`tests/test_dogfood.py:200-202`** — remove the `{"constraints_cap"}` allowlist,
  which existed only to tolerate the key above.

## 5. Carried, and what needs Paul

Four pool items, none scheduled here: the plan-review motion guard blaming the
reviewer for the lead's tree motion (9c2a3e9f); deleting `--in-place`, which Paul
raised and which two independent defects now support (128d0eb6); `corpus()` trusting
an `Archives:` line without checking the target's kind, so a hand-written block can
silence a LIVE BUG (3f3bf7a0); and constraint 11's enforcement moving from filing time
to push time, where a name-selecting falsifier can still forge a bug (5e5e6a21).

Two need Paul's decision rather than a lead's. **The free-lane dead end** (af931c00):
story-068 closed it for stories and left it open for free patches, because the card
deleted the route that covered it; both cheap fixes break something real. **The
archived-falsifier trade** (story-051): the batch no longer runs an archived record's
falsifier, which `DESIGN.md` had deliberately specified the other way, so "a dropped
debt that matters will red again" now holds only where a test tier already covers it.
