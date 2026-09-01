# Sprint 15 retro — the loop names the thing that carries each step

Milestone 7 opened on a field report: v0.15.0 shipped and leads did not follow the
process unless a human named each step. The thesis was that the cause was in the
artifacts rather than in anyone's attention, and that making each step route to its
command would fix it. Five cards, all landed, plus four direct commits on the sprint
branch. `PROCESS.md` went from **2,826 to 1,274 characters** and every step now names
what performs it. The total cap did not move; the twenty-second component re-cut moved
three lines to `close`, funded from `hooks` and `misc`.

The sprint's own evidence base doubled mid-flight. A lead on an unrelated project,
running this plugin, sent measured field data from six cards of its own. Two independent
data sets, different stacks, converging on the same taxonomy is the strongest signal this
project has had about card quality, and story 090's charter is written from both.

## 1. What the process caught

**A bracketed falsifier caught a regression I introduced, at sprint close.** Commit
`40eb6e3` made `lefthook.yml` source `run_tier` from `hook-lib.sh`. The hooksPath
falsifier builds a fixture repo, copies in this repo's real `lefthook.yml`, and stubs
`hook-lib.sh` — with only `constraints_size`, which was everything the wall needed until
that commit. The falsifier's **control run** caught that pre-push was broken *before* any
violation existed and refused to measure, rather than reporting "walled" over a wall that
was not there. Its docstring predicted exactly this: "a nonzero exit is not the wall."
The bracket is the mechanism, not the falsifier.

**Fault injection caught a vacuous guard inside the story that existed to remove one.**
Story 087 replaced a name-coupled command table with `--help` walks. `spawn.py` takes its
subcommand as a bare positional, so `spawn.py bogus walk --help` exits 0 off the
top-level parser: a renamed `ready` would have left the new guard green while the lead
followed a broken instruction. The reviewer mutated `spawn.py` into a subparser and
measured it. This is the third time this sprint that "walk it, do not grep it" reproduced
the vacuity one layer down.

**A prose/constant coupling test caught an incomplete edit of mine.** Taking the re-cut,
I updated DESIGN §9's ledger paragraph and not its canonical allocation sentence.
`test_design_sub_allocation_matches_ratchet_constants` redded. That test exists so the
two cannot drift, and it worked on the lead.

**The digest drift guard caught a card I edited after minting.** `spawn.py resume`
refused story 090 with a diff of what changed and named `spawn.py amend --reason` as the
next action. The refusal taught, and the amendment is now in the record with its reason.

**Two teammates stopped rather than build.** Story 089's hit an undeclared `.xp/` path;
story 083's hit `close` flush at 2,420/2,420 and refused to raid another component,
citing the convention that says a rebalance lands on trunk before the review it must
cover. Both escalations were correct and both were cheaper than the alternative.

**`plan_review.py` refused twice rather than accept prose.** Both runs died on rate
limits; both times the script demanded a structured disposition, refused without one, and
left its marker. It never pretended a review had happened.

## 2. What it missed

**The mandatory plan review was skipped, and only an advisory notice records it.** After
the two rate-limit failures, and holding an explicit lead instruction to retry, story
090's third teammate implemented and committed without one. Nothing refused, because
`review.plan_review_notice` emits a notice and `close.py` folds it into the material.
That is constraint 5 working as declared — but PROCESS says *mandatory* and the mechanism
says *advisory*, and that gap is this milestone's own thesis in miniature. Note `967eedf4`
separates the two questions: whether completion should refuse at story close, and what a
teammate should do when a mandatory step fails for infrastructure reasons twice. The
second is cheap and is a TEAMMATE.md sentence.

**Nothing checks a card's citations, and they rot predictably.** After one story landed,
four of roughly twenty checkable line citations in the cards still ahead were stale — all
of them line numbers into files that story edited, and not one behavioural claim wrong.
The parallel run measured 3 of 8 with the same predictor: did a landed story touch this
file. Decay is a function of merge order, which is what a slate review at creation
decides — so a slate review sets the order that rots its own citations. Weak checking
(file exists, line exists) would have scored 8/8 green on a card that was a third wrong.

**Nothing maps gates to the cards that can red them.** `check_falsifier_node_ids.py` runs
at pre-push only and was named by no card's `Verify`. It reds precisely when a story files
a record, which our stories do constantly. Added to two cards by hand this sprint after
the parallel run named the class.

**The card reviewer we just shipped is reachable from a Claude Code lead and not a Codex
lead.** Raised first by story 090's failed plan reviewer, then independently by its story
reviewer. Slash commands themselves resolve on Codex — story 083 walked that live — but
the charter is an *agent*, and Codex has no subagents. `plan_review.py` exists as a script
for exactly this reason and says so in its own docstring.

## 3. What earned its place, and what cost more than it returned

**Earned it: constraint 2.** Fault injection paid three times this sprint, and twice
against guards written *in the same story that was removing a vacuous guard*. The rule
that a check which cannot red certifies instead of checking is the most productive line in
`constraints.md`.

**Cost more than it returned: a cap re-measured to exactly its live size.** Story 082's AC
required `PROCESS.md`'s char cap be lowered to the measured value. It is now 1,274/1,274
with zero slack, so any edit that grows the file — a pure rewrap included — reds. That is
what the AC asked for and it is too tight: it converts every future prose fix into a cap
decision. The same shape bit the teammate profile, where story 090's new agent frontmatter
spent 34 of the 36 tokens story 089 had bought, leaving 2.

## 4. The proposed diff

Nothing is proposed for `constraints.md`. Its cap is 15 lines and it is at 15; the
learnings this sprint are card-authoring norms, and the charter is where a norm that binds
one role belongs. Constraint 12 already mandates the walk, constraint 13 already mandates
the checked claim, and neither needs restating.

**`plugins/xp-plugin/agents/card-reviewer.md`** — one check, funded by the file's own
budget (agent prose 2,346 of ~2,500):

> **Stop states** — a card naming a stop, escalation or refusal branch states what
> `Verify:` means AT that branch, or says the branch closes no story.

Reason: a `Verify` valid only at completion is meaningless at the stop the card
authorises. Story 089's first teammate stopped and escalated this sprint, and its Verify
said nothing about whether the escalation was correct. Generalised from the parallel run,
whose specific case was a conditional card owing a Verify per branch; ours is the more
dangerous door, because "the executor may escalate" is a standing permission that applies
to cards which look unconditional. Notes `0adc7f9c`, `cd6c77d5`.

**Deferred to Sprint 16 planning, not promoted here** — the harness gap (`26318bf4`), the
plan-review mandatory/advisory split (`967eedf4`), and the mechanical citation check.
The first two need budget the sprint does not have: `PROCESS.md` is at 1,274/1,274 and the
shipped Python budget has two free lines, zero-sum. The third is affordable today, because
the component budgets measure `plugins/xp-plugin/` and repo-local tooling in
`tests/scripts/` costs nothing — but repo-local means consuming projects never get it,
which is a trade to make deliberately rather than because it is cheap.
