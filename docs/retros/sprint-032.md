# Sprint 32 retro — findings decided, designs justified, reds preserved

Five stories landed in the original order: registry freshness, finding dispositions,
design guidance, human-question handling, and Verify evidence. After the disposition
story, two disjoint execution lanes overlapped; integration stayed serial. Independent
review fixed defects in every lane. No confirming-round waiver was introduced.

## 1. What the process caught

Whole-suite collection exposed seven stale slow-test registry IDs. The disposition
review found lost historical compatibility, hidden salvaged blockers, and leak checks
that failed to distinguish stdout from stderr. Fresh reports now state fixed, blocking,
reasoned drops and exceptional debt separately, while old reports stay preserved.

The budget transport fixture supplies its own verdict; it does not prove policy adoption.
Actual slate judgments in `/tmp/story-166-evidence/walk-codex/data-budget/slate-reviews/`
accepted zero debt in `sprint-0.round-1.md` and rejected over-ceiling debt in
`sprint-2.round-1.md`. `/tmp/story-166-evidence/walk-claude/evidence.md` records
zero-debt acceptance and over-ceiling rejection too. Both walked create-sprint files
match this release's shipped skill; these observations supply the policy evidence.

Design delivery checks caught omitted guidance and startup byte-budget failures.
Equivalent JUDGMENT/PROCESS compaction preserved the existing boundaries. The real
walks retained 28 initial plan/diff cases and 14 final diff cases across both harnesses;
correct simple controls stayed simple, and speculative hierarchies were removed.
A false control-flow finding was refuted against actual execution order. These are
judged observations, not a causal comparison of models.

Human-question review caught duplicate JSON fields erasing an unanswered question,
and historical capped blocks staying stuck after an answered amendment. Both fixes
have constructed red controls. Real consuming walks stopped on questions and reached
execution after explicit answers on both harnesses. Codex finished; Claude stopped at
handback on untracked pycache after committing. The evidence retains that limitation,
rather than claiming both walks completed close.

Verify review caught exited commands hanging on descendant-held streams and an evidence
locator truncated at a legal em dash in the path. Fault injection also exposed stale
receipts and success recorded before the final manifest was saved. Reds retain their
original bytes; logging failure cannot certify green. Post-review Verify and landing
checks passed for the accepted story fixes.

## 2. What it missed

RUNNING handoffs concealed dead native processes during the runtime interruption.
Actual PIDs and launch locks established that both lanes had stopped; explicit recovery
preserved their commits and stage artifacts. Daemon installation and permission changes
were temporally associated, but no terminating OpenAI API error or test-caused settings
change was proved. Launcher liveness, durable execution and interrupted resume remain
future issue work, including GitHub #162/#167's repeated amendment/review loops.

The lead began a command-walker commit before the active pipeline handed back. Spawn
stashed that draft and continued review. The lead stopped only the own commit process,
preserved the draft, then restored the reviewer's exact committed tree; no competing
lead implementation shipped. The late duplicate work illustrates ownership cost.
The lead also ended a turn after starting close checks and did not actively observe
their refusal until Paul asked. Background launch alone did not provide monitoring.

A historical falsifier constructed the old plan-report shape and failed before its
hard-wrapped-reason guarantee. The lead replaced it with the existing exact constructed
test using the new nullable-question contract. The fixture-isolation sprint-direct bug
was resolved on the landed tree. Their recurring guarantees remain active.

## 3. Judgment and cost

Paul authorized source-linked historical cutover, then Luna audit assistance. Three
read-only lanes audited all 972 entries; the lead retired 905 historical/addressed
obligations and explicitly dropped 60 nits or bounded corner cases. Seven entries
became five unscheduled options, pool cards 169–173, linked to existing issue work.
They are choices for planning, not a next-sprint commitment. The two investigation
options require full-path evidence and may be retired if existing safeguards suffice.

Reproduction establishes existence, not priority. Repo-only pytest checker policies
are not universal consuming-project contracts. Unsupported Markdown shapes, manually
malformed artifacts, cosmetic reporting and hypothetical advisory-boundary attacks do
not automatically earn machinery. Six old blockers were separately compared with
current code and constructed gate checks. The valid pre-rounds historical close frame
remains unchanged despite the current reader's compatibility warning. Detailed reasons,
source identity and scratch evidence are retained under the project data root.

A separate keep-ours backmerge discovery remains visible: the scratch red accepts a
release that discards a peer's change. It is dropped from this sprint's implementation
scope under Paul's next-sprint direction, not claimed fixed. Original evidence remains
available alongside the issue and pool choices. Recurring resolved falsifiers are kept;
this cutover does not forfeit their guarantees.

All configured seats used Codex gpt-6.1-sol. Claude consuming walks tested the shipped
product outside those seats; user-authorized Luna close assistance was also separate.
Findings, rework and interrupted time cannot establish a causal model benchmark.
Restore only the saved baseline role assignments after release and close.

## 4. Proposed diff

The executable changes are the five landed stories and the v0.33.0 release artifacts.
No additional constraint, charter rule, sandbox boundary or automatic confirmation
stage is proposed. The notes are promoted into this retro or the unscheduled pool,
with original evidence retained. Historical judgments have concise active records
linked to the complete per-entry reasons; superseded verbose records are archived.
The manifest and CHANGELOG name v0.33.0 before review and tagging. Cumulative review
and the shipping-tree full tier remain the release boundary.
