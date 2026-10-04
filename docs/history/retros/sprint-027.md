# Sprint 27 retro — "Resume the legs already green, and measure where the time goes"

Paul set wall clock as the primary goal at planning. Two cards, one config commit: 147 (#109,
config-declared legs that land receipts per leg and resumes), 148 (#114, per-invocation logs and a
timing ledger rendered at start and post-merge), and `[sprint-direct]` 50dea4d (the story tier
became the fast tier). Both cards closed in ONE review round with zero lead fixes to story code.
Milestone 15 closes here, at v0.28.0.

## 1. What the process CAUGHT that we would otherwise have shipped

**The new instrument found a silent leak on its first reading.** The first live timing table at
`sprint start` held 23 failed 0.0s `agent` lines named `story-042-review`. Two tests
(test_plan_review.py and test_spawn_run.py's reviewer-bound test) called `run_agent` with no
`XP_DATA`, so every suite run wrote into the REAL data root. It had done so for months (the
leaked `story-042-review.log` predates this sprint), invisibly, until a ledger made it countable.
Both are fixed in `[sprint-direct]` commits, measured red (+1 ledger line per run) then green (+0
over a full suite).

**Slate review falsified premises the maps missed, even with consumers asked for.** Round 1:
- the dogfood walk would red test_dogfood;
- the shipped append-only log contract was pinned by two tests;
- the timing table at `start` could not see the sprint review or land.

Round 2:
- `config_block_value` silently drops duplicate leg names;
- release records hold no time, and file mtimes lie by up to 40 hours.

**Story reviewers each caught a live-data defect.** 148's reviewer ran the new table against our
real release records: every tag date carries a local offset, so the table would have failed on all
five. 147's reviewer found four vacuous tests and a dry run that sent the lead to resolve a
conflict that did not exist.

## 2. What it MISSED, and which mechanism should have caught it

**The test-isolation leak predates every mechanism we have.** conftest.py strips inherited `GIT_*`
variables "so a test added later inherits the isolation", but nothing does the same for `XP_DATA`.
Nothing checks that a suite run leaves the real data root untouched. The timing ledger is now that
check, by accident. A cheap wall would be a conftest guard that points `XP_DATA` at a temp dir
unless a test sets its own. Recorded for the next slate, not done here: it changes the environment
of every subprocess-driving test.

**My mapper missed a pin on the config commit.** A job rename was reverted because
test_ratchet.py:327 pins `full-tests`. That job now runs the story tier under a misleading name.

## 3. Which rule earned its place, and which cost more than it returned

**EARNED: measure before cutting.** Suite time per story land fell from 6-8 min to 2.5-4.3 min,
and milestone-done from 6 min to 6.4 s. Sprint land's tier is now two legs, so a late red re-runs
only the leg that failed.

**EARNED: the two-round slate cap, again.** It forced three scope decisions to the lead instead of
a third round.

**COST MORE THAN IT RETURNED: nothing new.** One observation: GitHub issue #128 (a version bump
after review forces a confirming round) came from Paul mid-sprint and was recorded, not scheduled.
This close bumps the version BEFORE the review to avoid it.

## 4. The proposed diff

`.xp/config.yml` (ours, not shipped): `tests.full` and `tier_coverage_pins.full` become
`pytest -q -n 6 -m "not slow" && pytest -q -n 6 -m slow`, and a `full_legs:` block declares
`not-slow` and `slow`. That is story-147's walk, and this sprint's land runs it through the repo's
`close.py`. No constraint changes. Records: 6 notes triaged (all dropped as decision records or
loud residue); all 78 resolved records kept.
