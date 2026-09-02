# Sprint 16 retro — the batch caught what six clean reviews could not

Milestone 7's last sprint. Six cards, all landed, plus six direct commits on the
sprint branch. Every story review returned **0 blocking** except one, and every
one of the six still found a defect the suite could not — yet the three defects
that stopped the release were found by none of them. That asymmetry is this
retro's whole subject.

`story-091` closed the milestone's thesis and proved it the only way it could be
proved: a live Codex lead, no `--plugin-dir` and no subagents, reached a real card
review through the shipped runner, its retries JOINED pid 55415 rather than
launching a second reviewer, and the review returned **RED on story-091 itself**.
A mechanism that can falsify the card that created it is not bookkeeping.

## 1. What the process caught

**The fresh-reviewer mechanism, by RUNNING things rather than reading them.** Four
of six stories had a guard that could not red against its own target, and in three
the reviewer found it by executing something: simulating a card in a disposable
copy, running against the REAL data root, or driving a stub reviewer.
- `story-093` — `land` swallowed an unreadable launch marker and merged on an
  earlier green round. A truncated marker is exactly what a host kill leaves.
- `story-084` — the `no open card -> /sprint-close` row was unreachable on any
  repo that had ever closed a story, because handoff markers persist by design.
  Proved against this repo's own 24 markers; the test greened only because its
  fixture built a state the real system never reaches.
- `story-091` — a card reviewer could **rewrite the slate it was judging**,
  undetected: `plan.md` lives outside the repo, so `tree_state` never saw it.
  Proved live with a smuggled `[ready]` card at `rc=0`.
- `story-085` — its own new skill's word cap had slack for 36 words of the content
  that cap exists to forbid.

**The sprint-close falsifier batch, three times, on defects no story owned.** This
is the finding. Each red was a CROSS-STORY or OUTSIDE-THE-REPO property, which is
precisely what a per-story reviewer structurally cannot see:
- the commit gate had grown past usable — no single story made it slow, 1,129
  tests did;
- a record named a test that `story-086`'s extraction had moved, and the checker
  that exists to prevent exactly this ran GREEN through all six stories because it
  only looked for `-k`;
- two shipped comments cited `constraint 15`, which names a rule here and resolves
  to NOTHING in a consuming repo — *ours 14 constraints, a freshly scaffolded
  consumer 4*. Both citations were written by story reviewers, reasoning correctly
  inside our numbering.

**Field reports, again, and they beat us to three defects.** Issues #45 and #46
and divineruin's plan-review report each named something invisible from inside:
our cards never backtick a `Files:` line, our lefthook runs `secrets` at pre-push
while the shipped template does not, and our suite stubs the harness so it cannot
answer whether a real teammate reaches a real plan review.

## 2. What it missed, and which mechanism should have caught it

**`check_falsifier_node_ids.py` should have caught the stale node id and did not.**
It REQUIRED an exact node id and never checked the node still resolves — implementing
half its own docstring. The expensive gate that runs once at close caught what the
cheap gate that runs on every story exists to catch, which inverts what each is for.
Fixed this sprint (`531a098`): node ids are now verified against one `--collect-only`,
with the negative case `test_work_falsifier.py` never had.

**Card review does not verify record ids.** `story-084`'s card cited falsifier
`0f7ac317`, which exists nowhere. The card reviewer reads code well — it found a
circular budget plan, a false line-number citation, a component mischarge, and
simulated `story-086` to find a false green — but a record id is a MECHANICAL,
checkable claim and no mechanism checks it. Nothing in the pipeline can: an id
naming nothing is not a red, it is simply never checked.

**Walk records could not be tied to a commit, twice.** `story-091`'s pinned
`6774320` while `eb27580` then changed the runner beneath it; `story-085`'s recorded
a version and a date. I then filed the note warning about this and made the same
mistake on `story-086` three hours later, labelling the record with the story's
commit while validating wording its reviewer's patch had introduced. Its reviewer
caught it. A walk is the ONLY evidence for a constraint-12 claim the suite cannot
make, so a record that cannot be tied to a commit proves nothing about what ships.

## 3. Which rule earned its place, and which cost more than it returned

**EARNED: fault injection on every new guard.** It is the single mechanism behind
almost every finding above. It also caught two of MY changes this sprint — an
"archive" bug that was a designed capability pinned by an existing test, and a
node-id matcher that called four live records stale.

**COST MORE THAN IT RETURNED: the fast tier's TOTAL ceiling.** It has now fired
twice, at 258->691 and at 691->1,129, and BOTH times on healthy growth at flat
per-test cost. It has never once fired on a real slowdown. The per-test bound is
the invariant that survives growth; the total is a product question — "will a
human still wait for this" — wearing a tripwire's clothes. Re-cut to 180s at
`640b308` with the reasoning recorded; a third re-cut should not happen.

**MEASURED, and it reframes the cost debt: the fast tier is SUBPROCESS-bound.**
`-n 8` 129s, `-n 12` 222s, `-n 16` 349s over the same 1,129 tests — monotonically
worse, because every worker multiplies `git`/`claude`/`codex` spawn contention
rather than parallelising CPU. A stub from a five-day-old pytest session was still
alive on this box. Future speed work belongs on spawns per test, not concurrency.

## 4. The proposed diff

1. **DONE — `plugins/xp-plugin/agents/card-reviewer.md` item 3** now reads
   "execute existing-code claims and RESOLVE every cited record id ... an id naming
   nothing is never a red." That is where the check is PERFORMED, so it is the
   cheapest place it can live.

2. **NOT DONE, and the reason is the point.** This retro first proposed extending
   `.xp/constraints.md` rule 13 to record ids and asserted it "displaces nothing,
   it is a clause on an existing rule". MEASURED WHEN I WENT TO WRITE IT:
   constraints.md is 4,483 chars against a 4,500 cap — **17 free**. It displaces
   something, and the rule that every addition displaces one is enforced by the
   wall at every commit. A charter line covers the actual failure at no
   constraints cost, so the constraints edit waits for a planning re-cut rather
   than evicting a rule tonight. The false premise is left visible because it is
   the retro's own instance of the defect it is about: I wrote down a claim about
   a budget without measuring it.

3. **A walk record names the commit walked AND whether it still ships.** Smallest
   home is `templates/` or the close prose; three walks this sprint, two unusable
   as evidence.

NOT PROPOSED, deliberately: no rule about the total-ceiling re-cut. The docstring
now carries its own ledger and the argument for retiring it, and a constraints
line would be a fourth copy of a decision that already has three.
