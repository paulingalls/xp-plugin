# Sprint 7 retro — the harness cannot silently fail to do the work

Eight cards landed: 049, 035, 048, 038, 045, 036, 047, 043. Milestone 3 closed.
Four releases shipped alongside (v0.7.4–v0.7.7), three of them from defects the
sprint's own work surfaced.

## 1. What the process CAUGHT — the mechanism, not the finding

**Fault injection at story close, and it is not close.** Constraint 2 asks whether
a check can red against the defect it names. Reviewers ran that question against
each story's own new guards, and in FIVE cases the guard could not:

- **045** — `test_finished_fixture_copy_cost_against_git_build` printed a ratio and
  returned. Against pre-story fixtures: **1.01x, "1 passed."** It ran in two tiers
  that do not filter `slow`, so a fully reverted fixture would have been certified
  twice before the batch noticed.
- **047** — the reviewer reverted `build_sprint_bundle` to the full diff and **all
  94 Verify tests stayed green**. The card's central claim had no check that could
  red. Two more in the same story: deleting AC 3's delta section left its test
  green (it matched the diff's own hunk header), and deleting the round-2 candidate
  handoff passed *every* test.
- **036** — a round with `blocking: []` was the reviewer's own word that Verify ran.
- **038** — the new whole-line contract covered only the `workspace-write` arm; the
  `danger-full-access` arm, which is the **shipped default**, kept a substring check.
- **v0.7.7 (mine)** — I told both fixers to run `lefthook run pre-commit` over
  unstaged edits. Commit gates read the index: every check skipped, exit 0. I
  shipped a wall that inspected zero files.

One mechanism, five silent defects, four of them in the guard the story existed to
add. Nothing else we run finds this class.

**Second: the walls held under real pressure and named their own remedies.** Land's
overlap refusal caught 043 and 047 sharing `sprint_close.py` — and asked the right
question rather than listing files: *"ask whether two stories are sharing a file
domain, because that is what this refusal sees."* The ratchet caught the merged
`test_sprint_review.py` at 520/500, and 047's round had already predicted that exact
failure and named `TestConfirmingRoundScope` as the leaf to extract.

**Third: the falsifier batch found two rotted records before it found any code
problem** — a falsifier whose test had been renamed out from under it, and a
retracted bug with no honest disposition.

## 2. What it MISSED, and which mechanism should have caught it

**Cards go stale under their own sprint. Three instances, all shipped into
teammates:**

| card | the stale claim | found by |
|---|---|---|
| 045 | Files omitted the fourth `make_repo` (93 call sites) | the executor |
| 048 | AC required v0.7.2 on a premise its own card contradicted | me, at close |
| 043 | Verify named neither suite 036 had just created | the plan reviewer |

The card review runs **once, at sprint open**, and nothing re-checks a card against
the tree it will actually branch from. `spawn.py ready` is that moment and it
currently only mints a digest.

**A vacuous gate reached a release commit** because free patches are card-less —
no AC, no Verify bound what v0.7.7 promised. Its own reviewer named this.

**Note triage has not run for three sprints.** 141 notes queued at this close; 83
predate Sprint 7. The step is in the skill and nothing measures whether it happened.

**Neither reviewer flagged an empty commit body** on 043 or 047, though VALUES binds
commit messages explicitly.

## 3. Which rule earned its place, and which cost more than it returned

**Earned: constraint 2.** See §1. It is the highest-yield rule this project has.

**Cost more than it returned: constraint 11's `-k` prohibition, as PROSE.** It
states the failure exactly — *"a falsifier coupled to what the code is CALLED reds
when someone renames it"* — and we have now shipped it four times (note `f29d2ac`,
three in an earlier sprint; `ed4b4329`, this one). A rule that is written, correct,
cited, and violated at the same rate as before is not paying for its line. It should
be enforced by the append CLI, not remembered.

## 4. The proposed diff

**A. `constraints.md` #12 — clarify, do not add. No displacement needed.**

```
 12. **A path we do not execute is not verified.** We are the only user and our tests
     build their own fixtures, so shipped surfaces go unwalked. Before releasing a
-    surface a consuming project uses, walk it end to end. Walking it costs minutes.
+    surface a consuming project uses, walk it end to end. PROSE THAT INSTRUCTS AN
+    AGENT TO RUN SOMETHING IS SUCH A PATH: run it yourself before shipping the
+    instruction (measured: v0.7.7 told two fixers to run a gate that inspects
+    nothing). Walking it costs minutes.
```

**B. `work.py` — enforce constraint 11 rather than restating it.** Refuse a
falsifier whose pytest invocation uses `-k` instead of a node id. One check, at the
one place every falsifier is born. This displaces nothing in constraints.md because
the rule is already there; it moves it from prose to mechanism.

**C. Not promoted, carded instead:** card-staleness at `ready` (needs a design
decision about what `ready` re-measures) and the missing "filed in error"
disposition (story-051's scope, now widened by `d1948070`).

## 5. What carries

18 live debts and 141 untriaged notes go to Sprint 8's planning, where the pool
already holds 052–056 drafted from this sprint's records plus the six carried cards.
The untriaged backlog is the first thing that close should shrink.
