# Sprint 25 retro — "Nothing is lost to an upgrade, a card edit or one broken container"

Three cards, five GitHub issues combined by shared surface at Paul's request: 141 (#121, a
hook whose plugin version was deleted mid-session still runs), 142 (#113 + #123, a card edit
cancels a story review early and salvage offers no reset over commits it cannot attribute),
143 (#119 + #120, land checks the manifest before the tier, and one broken environment files no
bug). All three ran in parallel lanes and closed in ONE review round each, none blocking.
Milestone 13 closes here, at v0.26.0.

## 1. What the process CAUGHT that we would otherwise have shipped

**Mapping before authoring removed the premise errors.** Four read-only research agents
executed and read each issue's surface at `ed0185f` before a card was written. Slate review
then falsified NO claim the lead wrote about existing code — against five at Sprint 24. What
it found instead was the class reading cannot close: omitted pins on every card (a prose test
pinning the reset offer, 115 land calls on a fixture the version check would refuse, a Spend
line naming one of three components).

**Slate review round 2 made ACs able to red.** story-141's fallback had to pass the sibling's
stdout and exit status through unchanged — a fallback that swallowed stdout would have silently
dropped every Stop block after an upgrade, the exact symptom the card fixed. A 0.23.2/0.23.10
fixture made a lexical sort red.

**Close review caught a vacuous test and a torn read.** story-143's "no falsifier ran"
sentinel could never fail (it `touch`ed an existing file, and a green tier trusts deferred
falsifiers without running them). story-142's watcher would have cancelled a healthy review on
a half-written plan.md; it now needs two agreeing polls.

**The counter-control made the walk mean something.** The Codex-fired walk passed on the new
commands; the same walk on v0.25.0's commands reproduced #121 — and showed Codex reports a
missing hook script as BLOCKED, so an upgraded live session stalled at every Stop.

## 2. What it MISSED, and which mechanism should have caught it

**My first walk fixture was wrong.** With two versions installed at session start, Codex picks
the highest as the root, so a pre-staged sibling tested nothing. The control run caught it,
which is what a control is for; the walk then staged the upgrade mid-turn, as in the field.

**story-142's "extract before growing" was not followed.** review.py went 495 -> 496 and
spawn.py sits at 498/500. Constraint 8's hard cap is the only wall; a card's instruction is
advice. The next card touching either file hits the cap and must extract.

## 3. Which rule earned its place, and which cost more than it returned

**EARNED: the no-lead-fix-at-close rule (Paul, Sprint 24).** Zero lead fixes, zero confirming
rounds, three cards at one round each. Sprint 24 ran seven rounds for four cards.

**EARNED: Verify names the new test file at authoring.** Every card declared its new test file
in Files and Verify; the gap that hit 3 of 3 stories last sprint did not recur.

**COST MORE THAN IT RETURNED: nothing new.** The slate reviewer's retired Mutation check was
not missed: both rounds probed by running code in /tmp and still falsified what mattered.

## 4. The proposed diff

None. No constraint gains or loses a line. Records: 7 notes triaged (1 superseded, 6 dropped);
all 78 resolved records kept (`2b5a456d`, 124s, is the fast-tier cost guard).
