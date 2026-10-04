# Sprint 29 retro — "The cheap gate first, the failed gate again, and a refusal you can read"

Eight field issues from the consuming clones (#135–#142), in six cards and two serial lanes:
- land lane: 153 (#135, #138), 154 (#136, #141), 155 (#137), 158 (#142);
- spawn lane: 157 (#140), 156 (#139).

Paul ruled on every open design question at planning, and each ruling is posted on its issue. The
legacy lead answered the questions on #137–#141 by message before any card was written. 158 was
added after open with Paul's ruling, and it never had a slate review. Every story closed in ONE
review round with nothing blocking. Milestone 17 closes here, at v0.30.0.

## 1. What the process CAUGHT that we would otherwise have shipped

**Slate review round 2 found a hole in a constraint-14 wall that already existed at HEAD.** The
free-land version wall read git tags only. In the window between a release PR merging and its
tag being cut, a second free release at the same version passed the wall and the trial merge. On
the merged path this already slipped through at HEAD. The only thing still stopping the unmerged
path was the overlap check that 153 was about to exempt. So the card as written would have
removed the last guard. Round 2 made it RED before any code existed.

**Asking the reporting agent, and then measuring, changed what we built:**
- The legacy lead's answers turned #137 from "a missing marker" into "repair never covered a
  land-time red", and downgraded half of #140.
- Measuring all five consuming clones reversed a verdict I had taken from this repo alone. The
  #142 skip is worth about 105 min per sprint in legacy, against about 3 min here.

**Story reviewers fixed real defects in their own round:**
- 156: a retry refused over its own tier-run leftovers, and exit 127 read as a red.
- 158: the receipt was never deleted, and a malformed `Verify reads:` line was not caught until
  after a review had run.
- 154: the stubs hard-coded `/usr/bin`, and pnpm's patch file was missing from the dependency list.
- 153: two tests could not fail.

## 2. What it MISSED, and which mechanism should have caught it

**Story land runs only the fast tier, so broken slow tests land.** Stories 153 and 156 each landed
a change that turned a slow test red:
- 153's reviewer patch changed a shared fixture.
- 156's new spawn gate used up a one-shot test gate.

154's land Verify caught 156's break, on 154's land. I fixed both tests in `[sprint-direct]`
f12d19b (bug 304879f3). 158's executor did the same again, and its reviewer caught it by running
the slow tier. The cost was about 15 minutes, once.

Paul's call is to accept this. The sprint-land full tier is the wall. A slow run before every land
would cost about 24 min per sprint to save that 15.

## 3. Which rule earned its place, and which cost more than it returned

**EARNED:**
- **Measure the consumers, not just us** (Paul, this sprint). It reversed one verdict and sized
  another.
- **A feature is in scope when it is the better fix** (Paul, this sprint). It produced
  `Verify reads:` and the slate-review nudge for new optional card fields.

**COST, KEPT KNOWINGLY:** the executor now runs `tests.story`, and spawn runs it again at
handback. That is one duplicate run per story: 1.5 min here, 4–5 min in legacy. It stays because a
red found at handback costs an executor relaunch, and legacy saw four story-tier reds at land in a
single sprint.

## 4. The proposed diff

None to constraints, config or charters. The shipped changes are in the v0.30.0 CHANGELOG entry.

Records:
- bug 304879f3 resolved (its two tests, covered by the full tier);
- 23 notes archived at triage, two of them promoted: one into the #142 ruling, one into the
  CHANGELOG's external-state trade;
- the 77 resolved records kept (166 s together).

#143 (a repo-configured `preflight:` command, from legacy's lead) is filed for Sprint 30.
