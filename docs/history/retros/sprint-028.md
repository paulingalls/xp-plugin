# Sprint 28 retro — "Bump before the review, keep tests out of the real data root, stop pointing at a dead slate review"

Wall clock stayed Paul's primary goal. Four cards in four disjoint lanes:
- 149 (#128): check the version at review launch; exempt a release bump at land; free land checks too.
- 150: a conftest guard keeps the suite out of the real data root.
- 151 (#122 remainder): a dead slate marker after open is not the next action.
- 152 (field evidence from legacy2): a card that only grew is not drift.

152 was added at planning after a consuming project's lead reported 3 of 5 lands refused. #111
and #112 were closed with measured reasons. Every story closed in ONE review round with nothing
blocking. Milestone 16 closes here, at v0.29.0.

## 1. What the process CAUGHT that we would otherwise have shipped

**Asking a consuming project's agent turned a guess into a defect in our own charter.** I guessed
the refusal Paul saw came from a hand edit. legacy2's lead reported it came from pipeline stages
following our EXECUTOR.md ("extend Files and report"), which every land then refused. The fix
makes the charter true instead of rewording it.

**Slate review, both rounds, again.** Round 1 made three cards RED:
- 149's free-land check would have broken three free-leg tests;
- 151's recovery-block half needed a file at 488/500;
- 152's growth tolerance would have let whoever edits a card lift the `.xp/` fence.

Round 2 found that two review tests passed only because review never checked drift. Under the
two-round cap, all of it was fixed by hand.

**Story reviewers fixed small things themselves:**
- 149: a false ".xp/ only" line printed next to the release-bump line.
- 150: a real-root resolver that no test pinned.
- 152: a Verify-extension test that could not fail.

## 2. What it MISSED, and which mechanism should have caught it

**Running four stories at once, which I scheduled, filled the disk.** I treated "no shared
declared file" as "safe to run in parallel". The data volume sits at 95% at baseline. Other
projects' iOS runs had left 156 GB of Maestro and xcrun temp files, which have since been cleaned
up. The fast tier took 21 minutes instead of 2, 152's executor could not commit, and 151's reviewer
patch failed its commit gate. All of it recovered one story at a time with nothing lost. The
redone agent work, from timing.jsonl, was 152's second executor (829 s) and 151's second reviewer
(362 s), plus 151's commit gate re-run. No mechanism owns machine capacity, and I am not proposing one: the
cause was external and is gone. I did not measure whether running two stories at a time would
have beaten four.

**Refreshing cards in parallel collides.** Four refreshes of different cards in one `plan.md`:
one was refused because text outside its card changed. It was loud, and a rerun fixed it.

## 3. Which rule earned its place, and which cost more than it returned

**EARNED: map first, including consumers.** Five read-only mappers, plus a lead re-read of
every cited range, gave slate premises that held. Every RED was an omitted pin or a design
consequence, never a false claim about code.

**EARNED: refresh a card just before its spawn** (Paul, this sprint). All four refreshes corrected
line numbers that had moved since the slate was written.

**COST MORE THAN IT RETURNED: the fast-tier cost falsifier (2b5a456d).** It re-ran the whole fast
tier to prove the tier is fast: 197 s of a 391 s close batch. Paul dropped its replacement debt on
2026-09-08; the resolved record kept running. It is archived now. `timing.jsonl` (v0.28.0) records
every story land's tier time, so a slowdown is observed there instead.

## 4. The proposed diff

None to constraints, config or charters. One `[sprint-direct]` refactor: 468b23e shares the
Files-field boundary between `review_scope.py` and card growth, closing the latent drift story-152's
reviewer noted. Records: 12 notes and 2b5a456d archived (its now-unowned script and unit tests
retired in `[sprint-direct]` 3df7b75, which the script-ownership test demanded); the other 77 resolved records kept
(about 3 s together).
