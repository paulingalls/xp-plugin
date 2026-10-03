# Sprint 33 retro — amendments confirm the work they change

Four stories used four of six slots with no scheduled debt. Paul chose the plan-review
flow first and retained completed-executor reuse. Fresh GitHub #162/#167 comments
supplied the field evidence; the reported repeat hours are an observation of the older
release, not a measured improvement from this sprint.

## What changed

Accepted reviewer edits to a card or execution plan now move forward with their bound
findings. They do not trigger another amendment or plan review. An explicit human
question still stops execution. A later lead amendment receives a fresh
confirm/replan/block judgment before a replacement planner is considered.

Completed implementation is reusable only with intact completion evidence and a fresh
explicit judgment that the amended requirements need no implementation. Tree, card,
reviewed artifacts, successful stages and gates remain bound. Required gates and
independent diff review still run. Changed behavior reaches an executor. Resume preview
shares those choices and current findings with live execution, refuses stale evidence
consistently, and reports unknown future findings honestly.

## What feedback caught

Story review corrected authority to discard a reviewed plan and misleading refusal
recovery, submodule and embedded-repository fingerprints, reuse despite failed or
missing stages, and a malformed stored card crashing recovery. Preview review found live
execution omitting a findings-identity check and a writer fault test that could pass
from bytecode regeneration. A no-op control now separates that incidental write from the
actual handoff mutation.

The combined-tree checks caught a preview claiming execution while live reused it, and
an accepted-candidate check lost in the first merge resolution. Both had actual reds
before correction. Native transport comparison also exposed harness argv preparation
differences. Fault injections construct the refusal or state-write defect; syntax
failures and missing-test exit 5 were not counted as behavioral reds or greens.

## Evidence and execution cost

Both harnesses ran real installed consumer sequences with model-authored plans,
execution and independent reviews. Final 176 and combined 164 walks retain source
hashes, stage counts, tree identities, current Verify and outputs. Evidence-only
amendment used one planner and one executor; a later value change invoked the second
executor and changed output from 17 to 18. Each sequence ended with one planner, three
plan-review/confirmation calls, two executors and three independent reviews. 164
previews preserved file bytes, modes and modification times and selected reuse or the
pending confirmation before the corresponding live path ran. A Claude scratch review
strengthened a guard test inside its review round. These are behavioral observations,
not a causal model or time benchmark.

Paul authorized 164 to overlap 176 in separate worktrees. The initial 164 plan made 176
a prerequisite for all work; a sequencing amendment allowed independent work while
retaining the combined ACs, Verify and final review. Integration stayed ordered: 176
first, then 164. The partial 164 review honestly blocked missing dependency tests; its
commits and diagnostic evidence survived integration and the combined review. The
overlap incurred a partial review and a shared orchestration conflict. It did not waive
the dependency or certify the partial tree. Card observations are retained under the
data root. Paul requested checks at least every five minutes; one check gap during the
lead audit exceeded that limit. Frequent polling was later reduced at his request. The
partial review was avoidable sequencing overhead, not a required plan-edit review loop.

## Test feedback cost

Paul challenged nine-to-thirteen-minute tiers repeated at executor handback, commit,
land and push. The slow registry still described a September 18 census, while new
subprocess-heavy tests defaulted to fast. Commit and story tier were identical; the push
job misleadingly called itself full although it ran story. Repository prose also claimed
a full push suite even though full checks occur at sprint land.

The direct patch (2984877) removes twelve redundant registry/parser cases: six duplicate
matrix combinations, four marking cases already exercised by the full-collection
positive controls, a whole-repository sidecar cost pin, and a weak node-spelling check
subsumed by exact collection validation. Serial/parallel modes, each marker, path
spellings, partial-selection boundaries and all registry mutations survive. The unmarked
mutation now targets the stronger collection/body check. Baseline registry/parser checks
passed all 42 cases before pruning; the retained checks plus ratchet passed 50 after
pruning, including every registry mutation. The whole census passed 2,932 with four
skips and one precondition refusal: Verify evidence reported EPERM while running true
before the dirty-tree case was constructed. Its exact isolated recheck passed. That
refusal is retained as measured evidence, not relabelled a full green or hidden by
disabling a check. Collection is 2,949 -> 2,937: 845 fast product, 1,912 slow product,
and 180 meta cases. A 0.5-second measured cutoff replaces 1.0 seconds. The enabled
commit hook passed 841 tests with four skips in 47.97 seconds overall (pytest 42.82
seconds); 164 land previously took 816.95 seconds for 2,217 fast-tier cases. These are
different trees/selections under varying host load, not an isolated speed benchmark.
Other projects ran concurrently on the host: load reached 195 on 16 logical cores.
Census timings are observations under load, not a quiet benchmark or a causal estimate
of normal latency.

Meta checks retain adversarial pressure at release while leaving the commit tier:
registry/parser machinery, fixture copies, ratchet/falsifier auditing and selected
injected guard mutations. Ordinary invalid-state product checks remain product checks.
The full legs select mutually exclusive fast product, slow product and meta populations.
Collection evidence constructs missing-meta and overlapping-meta selections to prove
that the coverage/disjointness checks can red. Commit, handback, land and push
intentionally recheck the cheap floor; no new bypass or untrusted certification cache is
introduced. This trades early feedback on expensive cases for usable commit latency and
full shipping-tree feedback at sprint close.

The first close batch also exposed an obsolete standalone lock falsifier. Its card
omitted required Files/Verify fields, so the current candidate contract refused before
the expected lock wait. Its hang guard exited but leaked a holder that kept the batch
capture pipes open. Native stack/FD evidence identified the owned orphan; cleaning it up
exposed the retained red, rather than certifying the stalled batch. The script
duplicated the existing valid-card lock-interleaving test. It is removed; work.py
resolution db96a6a0 repoints record 44a7d784 to that exact node, covered by full,
preserving the recurring guarantee without another standalone invocation. An installed
copy bypassing apply_card's lock failed the replacement at the held-lock assertion; the
original passed through work.py resolve. No shipped lock was changed.

## Roles and close boundary

After 174, Paul temporarily set all configured roles to codex/gpt-6.1-sol/medium. The
original assignments are committed in .xp/roles-before-temporary-codex.yml; restoration
changes only roles and occurs when requested, with no automatic deadline. Actual Claude
consumers used Sonnet independently of this workspace's role mapping. The sprint review
includes the config and backup diff. This user-selected pairing is a tradeoff in
independent adversarial pressure, not evidence of model superiority.

The executable changes are the four stories, repository test tiers/pruning, and v0.34.0
release artifacts. No new constraint or interruption/liveness scope is added. Notes
about roles and parallel sequencing and test feedback cost are promoted here; the
recovered unscheduled pool remains unscheduled. Current story and release checks,
cumulative review and shipping-tree verification remain the release boundary.
