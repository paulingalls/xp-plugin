# Sprint 3 retro — the close runs itself

Stories: 010 (size-ratchet), 017 (teammate spawn live + durable), 014 (the sprint
close marshals its reviews), 016 (the plan reviewer's duty to say no). 011 and 018
carried to Sprint 4. Six planned, four landed, and the two that carried were
carried for stated reasons rather than run out of time.

## 1. What the process CAUGHT that we would otherwise have shipped

**The spawned reviewer, repeatedly, on the story that was about it.** story-016's
close review found the walk fixture stated its own answer in the header the arms
receive — both arms would have "cut correctly" by reading, and the differential
the card pre-registers would have been unobservable. Round 2 found the transcripts
were spliced by a file-descriptor collision in the lead's own harness while the
record called them *verbatim*.

**The plan reviewer, on premises rather than plans.** story-018 was CUT at plan
review because its central claim — that spawn.py lacked a whitelist — was false
against HEAD; both its ACs already passed. The archive-verb plan was rejected
because it justified itself on "the reader half is live" and then wrote to a
different file than the one it read. Neither was a coding error; both were
unchecked assertions about existing code.

**The escalation path, twice, cheaply.** story-016's first teammate stopped at 74
seconds and $0.77 rather than guess between a card whose Context dropped arm 3 and
an AC list that still required it. story-014's teammate stopped on a card that
contradicted the sprint preamble. Both were defects the lead introduced folding
plan reviews into cards, and both were found by the reader who hit them.

## 2. What it MISSED, and which mechanism should have caught it

**Vacuous guards written by the lead — four in one sprint.** A test asserting a
pre-launch head capture that no mutation could red; a fixture guard that banned
four phrasings and passed a fifth; an "archived debt still runs" test true before
the feature existed; a fault injection placed above the code it meant to move
below. Constraint 2 names this class and the reviewers caught every one. What
should have caught them earlier is the injection itself — the lead ran it and drew
the wrong conclusion once, which is worse than not running it.

**Scope, on the story about scope.** story-016 added the plan reviewer's DUTY to
name what should not exist, and nobody applied that duty to its own card. A
two-arm experiment with a pre-registration and a negative control, to validate
moving one sentence whose downside is a revert: three review rounds and ~$40. Its
own plan review revised the walk instead of cutting it — the reviewer was reviewing
its own charter, disclosed, and the conflict is the likeliest explanation.

**Human pushback.** The human objected four times in escalating terms and nothing
in the process reads that. Every other value has a mechanism — Honesty has review
findings and falsifiers, Simplicity has the ratchet and the cut duty, Communication
has prose pins. Feedback has none, so the lead kept explaining, which was the only
move it had a mechanism for.

**Triage, for the third sprint running.** 104 records, 75 emitted at this close, 53
predating the sprint. Sprint 1 genuinely triaged and the decision had nowhere to
live, so it is textually identical to an untriaged note today. Seven bugs read as
open and are all fixed and green. Diagnosed and fixed this sprint: `work.py archive`
plus a filter on the emission.

## 3. Which rule earned its place, and which cost more than it returned

**Earned: the size ratchet (story-010).** It reds on a live number rather than a
remembered one, and it caught a density breach the same day it was introduced. Its
sub-allocation also survived being wrong in the lead's favour twice — the lead
claimed close was squeezed when work.py measures in misc, and the reviewer checked
the arithmetic rather than the claim.

**Cost more than it returned: the ≤524-word backstop on the plan-reviewer charter.**
Nothing derived the number, agent prose sits at 1,357 of a 2,500 budget, and the
charter body is charged to no measured budget at all. It pushed an agent toward
cutting two concrete duty-implementing examples to fit, and pushed the lead toward
cutting the five `Close review: deep` triggers. Back-pressure that trims muscle.
Deleted at close. The check COUNT stays: it pins a structural claim.

## 4. The proposed diff

**LANDED at close, both funded by trimming their own evidence parentheticals:**

- `.xp/constraints.md:11` — falsifiers name a test by NODE ID; `pytest -k <name>`
  matching nothing exits 5, so it is red only for lack of a name and greens against
  any later test given that name. Three corpus entries are `-k` selectors today,
  and story-018 is scheduled to rewrite the exact tests one of them names.
- `.xp/constraints.md:13` (new) — a claim about existing code is CHECKED before it
  is written down. Four instances this sprint: story-018's cut premise, and three
  in the archive-verb plan (ratchet's assertion, work.py's component, the reader
  half).

**NOT promoted, and why:** the walk-belongs-to-the-lead rule is one instance and
now lives on the card. `templates/constraints.md` was audited and is clean — all
seven items are project-neutral, and rules about OPERATING the plugin belong in
PROCESS.md, which already ships, not in a consuming project's code invariants.

**OWED, not written — the Feedback mechanism.** Every other value has one. The
honest candidate is one line in CLAUDE.md: a second objection to the same thing is
a stop, not a prompt to re-explain. It is prose, which is the weak instrument this
retro just criticised, and the alternative is a mechanism policing the lead's own
replies — which is the story that should not exist. Recorded as a decision rather
than shipped as a rule.
