# Sprint 21 retro — "The close spends what it must and keeps what it knows"

Six cards landed: 122 (open-sprint selection), 118 (batch disposal + tier coverage),
123 (tier reuse receipt), 126 (pinned-root writer guard), 121 (release PR record),
127 (the three bugs this sprint filed). story-125 was cut at slate review round 2.
Two patches shipped mid-sprint: v0.21.4 (#68) and v0.21.5 (#69). Full tier at close:
1,518 passed in 224.76s.

## 1. What the process CAUGHT that we would otherwise have shipped

**Fault injection killed two mechanisms before either was written.** Slate round 2
constructed, not argued, that story-123's SHA-equality condition cannot exist on the
pending arm — `overlap.gates()` measures trunk merged into HEAD, a tree with no commit
SHA — and that story-126's refuse-on-mismatch would fire on `install_status`'s fourth
verdict `stale`, which is the NORMAL state of this repo from every release-prep commit.
That card would have bricked our own release legs every sprint. Both were replaced
before an executor saw them, and story-123's reviewer later confirmed the replacement is
the tested one by injecting the ORIGINAL mechanism and watching a test red.

**The falsifier batch aborted the close on a leak I introduced hours after writing the
rule against it.** `card_text.py`, created during the back-merge extraction, cited
"constraint 8" in its docstring — an index that means a different rule in a consuming
project. Constraint 16 is mine, added the same day. The guard caught it; reading did not.

**`land` refused three cards until their declaration drift was recorded.** 122, 118 and
123 each had a `Files:` line that no longer matched what shipped, and each refused until
`spawn.py amend` recorded WHY. That is the plan-review credential doing its job.

**A prose guard refused a cut I was confident about.** Trimming PROCESS.md's script names
as "mechanism the refusals already carry" red three tests, one of which fault-injects the
literal `plan_review.py`. Those names are the routing a lead follows, and they are tested
as such. I was wrong and the tests said so.

## 2. What it MISSED, and which mechanism should have caught it

**A card can stop solving the problem that filed it, and every gate still passes.** With
issue #67 I rejected the half of the reporter's fix that was harder — mid-session refresh —
on a principle I never checked ("auto-repointing surprises a lead mid-leg") without asking
WHO does the reload. Paul does, deliberately, in his own session. There was nobody to
surprise. The card shipped, all six reviewer checks passed, and #67's actual case is still
open. Every check we run is an internal-consistency check: ACs map to Verify, premises
execute, pins are not omitted. **A re-scoped card passes all of them by construction**,
because the ACs are rewritten alongside the mechanism. Nothing asks whether the work still
closes the report that filed it. FIXED THIS SPRINT: JUDGMENT.md's new "New information"
rule, paid for out of shipped prose.

**Retiring a constraint broke two falsifiers and nothing knew.** Constraint 10's retirement
was checked against citations by index — four repointed — but NOT against falsifiers that
assert a constraint's TEXT. `88b3ce55` asserted the literal "Markers are always scoped" and
went red-by-absence; `1586226f` imported a renamed symbol and did the same. Neither defect
was back. `check_falsifier_node_ids.py` passed clean through both, because neither is a
pytest node id. The missing mechanism is its sibling: something that EXECUTES each
non-pytest falsifier's imports and asserted strings against HEAD.

**Three of this sprint's four field bugs came from a peer session reading our code**, not
from our own reviews. Slate review reads cards; it does not read the code the cards do not
name. That is by design and it is also the gap.

## 3. Which rule earned its place, and which cost more than it returned

**EARNED: the ratchet re-cut, but not in the way I argued for it.** I recommended re-cutting
every component to measured reality so the numbers would bind again. They did not bind — one
sprint later close is 3503/3003 and every component is over. What the re-cut DID buy is
attribution: because everything started at guideline, story-118's +210 and story-127's
growth were visible on the first run instead of hiding inside inherited overage. The number
did not constrain; it explained. That is worth keeping and worth being honest about.

**COST MORE THAN IT RETURNED: the component guideline as a line count.** It cannot tell 279
lines of new capability from the same rule written four times, so it gets moved rather than
paid. Measured this sprint: four `build_bundle` variants (67 lines), `git()` defined 3×,
`stamp()`/`marker_path()`/`fail()` 2× each, and FIVE separate instances of one-rule-two-
implementations found by reviewers — `declared_files`/`_declared_files`, `read_sprint_state`
vs raw `json.loads`, `edit_plan` vs an unlocked write, two different `release_tools`, and the
marker read at review/salvage. Duplication is the thing the budget is trying to measure and
the thing it cannot see.

## 4. The proposed diff — FOR PAUL, none of this is applied

**(a) A falsifier staleness check for non-pytest falsifiers** (note c47c6410). The sibling of
`check_falsifier_node_ids.py`: execute each falsifier's imports and asserted literals against
HEAD and refuse when one can no longer run, distinguishing "the defect returned" from "this
check is broken". Two live instances this sprint, both found by an aborted close rather than
by a guard. Sprint-22 card, not a constraint.

**(b) Reconcile `constraints_chars_cap` with `OUTPUT_CAP`** (notes 729c6183, 07423ac8,
e292dafb). The cap counts CHARACTERS and the hook budget counts BYTES; nothing relates them.
Our profile is 9,338/9,500 and was 9,491 mid-sprint — nine bytes. A consuming project sits
935 bytes over its real budget and cannot see it. The honest fix REFUSES their commits, so it
needs a migration path. Sprint-22 SLOT, not a patch.

**(c) Issue #67's mid-session upgrade is still open.** `refresh_env` runs only from
SessionStart, so `/reload-plugins` refreshes nothing. Paul's stated requirement is that it
JUST WORK. Shape: a Stop-hook root comparison, plus fixing `env.py`'s refusal, which still
tells a lead to start a new session.

**(d) NO CONSTRAINT PROMOTED, and the reason is arithmetic.** `.xp/constraints.md` is
4,497/4,500 — three characters — so any promotion must retire a rule, which is Paul's call and
a "different project" decision. The candidate carried from Sprint 20 (`d2d1506e`, a refusal's
remedy computed from the state its trigger tested) now has its third sighting and is the one
I would promote if a slot is freed.

**(e) NOTHING ARCHIVED from the 76-record disposal offer.** The two most expensive resolved
records (131s, 47% of the batch) share one falsifier: `falsifier_fast_tier_cost.py`, the
gate-speed guard. The fast tier is now 126s and climbing, which is precisely what it watches.
Trading that guarantee for two minutes is the wrong trade, and it is the judgment story-118
deliberately left to a human.

**(f) The fast-tier cost falsifier runs the fast tier to prove the fast tier is fast**
(debt cd240723, Paul's call at close). 131s of a 277s batch — 47% — immediately before
the close runs the FULL tier over the same tests. Three executions of one suite to assert
one is quick. The file already diagnosed itself: "per-test cost is what stays true as a
suite grows; 'will a human still wait for this' is a product decision that wants a
periodic review, not a tripwire that fires on success." The fixture arm is a real
constructed ratchet (13.5× over 25 iterations) and stays. The suite-bounds arm should
CONSUME a measurement rather than produce one — the fast tier already runs at every
commit through lefthook and nothing records what it cost. Recording elapsed and collected
count where the gate already runs makes the check ~0s AND better evidence, because it
would measure the real gate a human waits on rather than a re-run under different load.
Deletion is not the answer and was already tried: reverted at v0.9.0's review, because it
left three live records certifying a wall-clock claim with a check that never starts a
clock.
