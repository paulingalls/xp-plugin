# Sprint 24 retro — "The close wall: run the expensive proof once, and never buy an answer twice"

Four cards landed, all field-filed GitHub issues: 140 (#108, the full tier moves to land and
runs once), 137 (#109, a re-entered close keeps its tier evidence), 138 (#110, finders then
verifiers run concurrently), 139 (#106, a declared path absent at HEAD costs no refresher
agent). story-136's extraction landed sprint-direct at open. Four more sprint-direct commits:
codex roles to gpt-6-sol/medium, the slate reviewer's Mutation check dropped, concurrent legs
streaming to their own logs, and the plan.md milestone archive (data root, not the repo).
Milestone 12 closes here, at v0.25.0 rather than the MAJOR its plan named (Paul): land bumps
minor only.

## 1. What the process CAUGHT that we would otherwise have shipped

**Close review found a regression no card anticipated.** Story-138's third round measured
that Ctrl-C no longer stopped a concurrent finder: the interrupt reaches only the main
thread, each agent runs in its own session, and the pool waits for every leg. In the field
that is ~28 minutes of unstoppable agents under `danger-full-access`. The reviewer fixed it
inside its round and fault-injected both halves.

**Close review found eight validation checks that could each be deleted green** (story-137,
round 2) — one of them would have let an entry with outcome `"passd"` certify tier reuse.

**Slate review falsified five claims I wrote about existing code**, and round 2 falsified a
correction I made in response to round 1. Card refresh then falsified a claim the slate
review itself made (story-139: the refresher fixture was importable, so the "required"
extraction was not).

**The collection count caught a copied shebang** at story-136's sprint-direct extraction —
a library module made directly runnable, the exact defect test_direct_invocation.py guards.
The reviewer's disposable clone had reported the same count both ways and would not have.

## 2. What it MISSED, and which mechanism should have caught it

**Every card that created a test file left it out of Verify — three of three** (137, 138,
139). A green close Verify then certified none of the ACs; only the full tier at land ran
them. The story reviewer caught all three, and amend now re-mints a receipt with no agent,
so the cost is one lead amend. Paul's call: archive, the reviewer is the mechanism. Not
silent: land still runs the tier.

**Salvage offered `git reset --hard` over commits the reviewer did not make** (story-138
land). Following it would have destroyed a lead commit and a recorded round's patch. This is
site 3 of an old refusal-text lineage the Sprint-18 fix only half closed. Filed: GitHub #123.

## 3. Which rule earned its place, and which cost more than it returned

**EARNED: the reviewer fixes inside its own round, free.** Story-140 and story-139 closed in
one round each. Every extra round this sprint — four of them — came from the LEAD: a fix of a
loud finding at 137, a card amend while 138's round 2 was running (which refused the round and
discarded its patch), then re-applying that patch by hand. Paul objected, correctly; the rule
the skill already states ("YOUR fixes cost a confirming round") now binds the lead's reflex
too: file noted findings, amend only between rounds.

**COST MORE THAN IT RETURNED: the slate reviewer's Mutation check.** Round 2 took 29 minutes
and ran the full tier at least three times, building story-136's whole extraction in a copy
it then deleted. Three of its four mutation findings were reachable by reading; the fourth
was the card's own Verify run early. Dropped (7c22c9b); checks 2 and 4 stay. NOT YET WALKED —
the next sprint open is its walk.

## 4. The proposed diff

**None to constraints.md.** Nothing this sprint displaces a rule, and the one standing
candidate (d2d1506e, a refusal's remedy computed from the state its trigger tested) gained a
fourth sighting in #123 but still has no slot.

**Records**: 55 notes triaged — 4 superseded by this sprint's cards, 3 promoted (#123, #124,
the plan.md archive), 48 archived as decision records or loud residue under the post-v1
filter. All 78 resolved records kept; `2b5a456d` (124s of 286s) is the fast-tier cost guard.
