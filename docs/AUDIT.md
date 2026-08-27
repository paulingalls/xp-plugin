# xp-agents Audit

*An evidence-based accounting of what earned its keep, before designing the successor.*
*2026-08-19. Sources: the xp-agents repo, the SMM data stores for `legacy`, `divineruin`, and xp-agents itself, test runs in both consuming projects, and testimony from agents currently working under the plugin.*

---

## 1. The verdict in one paragraph

The plugin works. Both consuming projects are high quality by direct measurement — ~10,000 tests green, commit histories showing a level of test-skepticism most human teams never reach, review cycles that demonstrably catch real defects before merge. But the mechanism doing the work is narrower than the machinery built around it. The parts that earn their keep are the ones that create **independent adversarial pressure** on the agent's output (fresh-context plan/code review, executable acceptance, fault injection). The parts that don't are the ones that create **bookkeeping about** the output (content budgets, event-link taxonomies, force-close escape-flag matrices, pillar curation, sequential close pipelines). The successor should keep the pressure and delete the bookkeeping.

## 2. Footprint inventory

| Component | Size |
|---|---|
| Hook/CLI Python (`scripts/` + `smm/`) | 167 + 78 files, **~52,500 lines** |
| Meta-tests (`tests/`) | 760 files, **~191,000 lines** (3.6× the code they test) |
| Skills | 19 skills, **~21,000 words** of prose |
| Subagents | 7 agents, **~13,500 words** |
| Hook bindings | 34 across 16 hook events |
| Event taxonomy | 16 event types, 3 resolution-link types, 4 pillars with per-pillar caps, per-type content budgets |
| Releases | ~388 versions of accretion (4 changelogs, 620KB) |
| Doctrine docs | 4 (acceptance, branching, security, SMM design) + ARCHITECTURE + PROCESS_GUIDE |

Per-session context injection (measured against legacy's live SMM):

| Injection | Size |
|---|---|
| SMM four-pillar render | ~1.4k tokens |
| system_context render | ~4.3k tokens |
| PROCESS_GUIDE + XP_VALUES | ~2.3k tokens |
| session_history / LAST_SESSION | ~2.5k tokens |
| sprint.json render (current legacy sprint) | **~26k tokens** if fully rendered |

Plus ~0.13s of Python startup per hook invocation, several hooks per tool call, on every tool call of every session.

## 3. Does it work? Yes — measured

**Test suites, run today, all green:**

| Project | Suite | Result |
|---|---|---|
| legacy | packages/db | 2,051 pass / 0 fail |
| legacy | apps/api | 1,598 pass / 0 fail |
| legacy | apps/biographer (pytest) | 864 pass / 4 skip |
| legacy | packages/framing | 93 pass |
| divineruin | apps/agent (pytest) | 5,593 pass |
| divineruin | apps/mobile | 379 pass |

**Codebase scale:** legacy ~223k LOC across 13 packages, 3,944 commits; divineruin ~2,160 commits. Both real, shipping, multi-platform products (voice AI + mobile + web + infra).

**Quality is visible in the commits themselves.** Sampled commit subjects from legacy: *"the latch was proven to exist, never proven to arrive"*, *"a negative control that only checks the exit status is not a control"*, *"the capstone was asserting a guard that never ran"*. These are commits that interrogate whether tests actually test — the refactor/review step is doing epistemics, not formatting.

**Reviews catch real defects.** The most recent legacy retro records: a close review that fault-injected its own gate enforcer and found a false green (`--legs ','` split to zero legs, ran nothing, exited 0); three consecutive story closes catching rotted citations, wrong-file pins, and stale premises before merge; 224 concerns raised in one session, all commit-addressed.

The caveat (from Paul, mid-audit): tests pass *because they must to commit* — the cost has moved into **suite runtime and meta-test accumulation**. The open design question is not "do gates work" but "which tests run when" — balancing early catch against development speed. xp-agents already has surface-narrowing machinery for this; it is itself heavy.

## 4. What earned its keep — mechanism by mechanism

Verdicts: **KEEP** (core value, carry forward), **KEEP-SHRUNK** (right idea, 10% of the implementation), **RETHINK** (real problem, wrong mechanism), **DROP**.

### KEEP

| Mechanism | Evidence |
|---|---|
| **Fresh-context adversarial review** (plan reviewer, code reviewer, close reviewer) | The single highest-value mechanism, unanimously. A working agent testified to four findings in one session that self-review could not have produced, including a guard whose latch "was proven to exist, never proven to arrive" — 57/57 tests stayed green when the original bug was reinjected. The value is the *independence* (clean context, no authorship bias), not the checklists. Cross-CLI subagents (Claude ↔ Codex) would strengthen exactly this. |
| **Fault injection as a norm** | Seven vacuous checks found in one agent's own work in one session — *zero* found by reading. Explicitly the thing agents "would not do right without enforcement." Highest value-per-byte in the system: it's one constraint line plus reviewer pressure, not a hook. |
| **Executable acceptance criteria** | Story ACs as Given/When/Then plus `acceptance_execution` commands that must exit 0. "What stops done being an opinion." The story/milestone artifacts sampled from legacy are genuinely excellent — dense context, exact file domains, an executable definition of done per milestone. |
| **The planning decomposition** (execution plan → milestones with executable "done" → sprints → stories with ACs) | Legacy's milestone 3 sampled: goal, executable done-criterion, 9 change zones with per-file notes, impact zones naming the e2e tests that must keep passing. This is what makes big projects tractable for agents. |
| **Values as decision rubric** | XP_VALUES.md is 1KB — already right-sized. The conflict-ordering (Honesty > Courage > Simplicity > Feedback > Communication) does real work in review verdicts and retro classification. |
| **Red-first TDD** | Real value ("starting red requires two uses of the code") but smaller than expected per testimony — and the interesting failure mode (a red that's an unbound-variable crash, not the assertion's diagnostic) was caught by the *reviewer*, not the TDD gate. TDD is a practice to keep; the enforcement can be much lighter. |
| **Parallel teammates with per-task model/effort** | More done, more efficiently; worktree isolation works. The current tier-decision table (6 branches, pre-seed clobber rules, effort-latch clearing) is far heavier than the decision it makes. |

### KEEP-SHRUNK

| Mechanism | What stays | What goes |
|---|---|---|
| **Hooks as lane-keeping** | A handful of deterministic gates that cannot be argued with: tests-green-to-commit/stop, plan-reviewed-before-execute, secrets scan. Consistency is what builds trust. | 34 bindings → ~6. Friction observed in live use, with a caution: agent complaints don't always survive a code read. One agent called the lint hook "a bug-shaped trap" for linting already-staged bytes — the code shows that is deliberate and *correct* (the staged blob is what the commit carries; the agent forgot to re-`git add` after fixing). The residual real issues: the exit-status hook firing on fault injection *where red is the expected outcome*, and escape hatches (`# exit-status-not-needed`) discoverable only from error text. |
| **System context** | A short WHERE-layer (stack, test commands, architecture sketch) read by planners and reviewers. | 17k-token renders; 8 CLI modules for editing it; principle/convention caps with retire-before-add protocols. |
| **Session continuity** (kickoff/session summary) | A LAST_SESSION note. | The full session_history apparatus, GUPP injection prose, kickoff gate markers. |
| **Constraints pillar** | The one pillar with testimony of being load-bearing ("one line shaped an entire story"). | Intent/Risks/Wisdom pillars (read once or never, per testimony), curation watermarks, the housekeeper agent, pillar caps. |
| **Commit-closes-item linking** | `Resolves-Event:`-style trailer — mechanical, no judgment, works. | The three-tier STRONG/WEAK/STRUCTURAL link taxonomy and refutes-vs-references metadata rules. |

### RETHINK

**Concern/debt triage.** The pile-up is real and worst in the plugin's own dogfood: xp-agents 38/44 concern+debt events unresolved, divineruin 30/53, legacy 19/68. Legacy's sprints tell the story of "now" being picked too often: sprints grew from 6–11 stories (20–40KB) to 21–24 stories (108–115KB) as debt-stories were folded in; divineruin performed a late cull dropping 194 of 199 backlog items on the principle *"a defect with a symptom regenerates its own evidence"* — the right principle, arriving far too late. The current MAYBE-ADDRESSED heuristic matches on file overlap, which produced false positives "all session" (overlap ≠ resolution).

The working agent's proposal is better than now-or-never and answers Paul's urgency worry directly: **a concern must name its falsifier at creation** ("resolved when X reds"). Then triage is *running X*; a concern that can't state a falsifier is a note, and notes auto-archive. Pair with auto-archive-on-age (untouched N sprints → gone). This makes "never" the default rather than relying on an urgency the agent doesn't feel, and makes "now" earn its place with an executable claim.

**Retrospective / process improvement.** The retro artifacts are high quality (87 in legacy; Keep items cite event evidence and values) — but the Fix items show the loop not closing: "TDD gap, 4th consecutive session, still worsening: 5→5→7→8" recorded faithfully, session after session, changing nothing. The cost side is now measured: retro + housekeeper as full subagents at every kickoff ran **~115k tokens before any work started** in a live divineruin session, producing a Keep list of self-congratulation and a Try list where 3 of 4 items turned out to be already homed in existing stories. The adoption ledger (75 entries in legacy) tracks adopt/defer intent but adoption doesn't alter the *mechanism* — an adopted Try becomes a decision event, i.e., more prose injected, not a changed gate. Meanwhile work-selection carries a force-close matrix (3 deferrals → forced adopt/drop/date, with a convention-recording sub-prompt) — heavy process to manage process. The learning loop should either change something executable (a gate threshold, a lint rule, a test command) or say nothing.

**Sequential close pipelines.** A story close is ~15 turns of mechanical steps (preflight → domain check → push → PR → gate → counts → merge → mark done → events), of which exactly two need judgment: reading the reviewer's findings, and fix-vs-ask. Everything mechanical should be one script; the skill prose exists largely to sequence what a script would sequence deterministically — and the "Sequential Discipline" banners on every skill are compensation for that choice.

### DROP

- **Content budgets as hard-reject char caps** (200-char status, 350-char answer, …). Verdict carefully scoped: the *problem they solve is real* — models are wordy, and unbounded event prose is exactly how an SMM's token cost goes dishonest — and agents complaining about their own leash is the least trustworthy testimony in this audit (the first agent flagged that about itself). What the evidence actually indicts is the **mechanism**: hard rejection triggers rewrite loops that cost more tokens than the cap saves (~12 round trips in one session; one agent shaved 827→801 chars and was rejected again at >800), and the plugin's own `hook_errors.jsonl` files are dominated by its own validators rejecting its own agents' writes. The replacement isn't "no limits" — it's **declarative formats that make brevity structural**: a concern is `claim + falsifier command`, a decision is `choice + because`, a status is a file list. A field whose shape only fits necessary-and-sufficient content doesn't need a character count; where a free-text field survives, truncate-with-notice beats reject-and-retry.
- **file_domain as lane enforcement** — *verdict held loosely; see §6, this one is testimony-only in both directions.* One session amended domains 3× after the fact ("documents rather than constrains"); another rates the cross-story collision validator the best cost/value in the system. Worktree isolation already provides hard conflict safety for parallel work; the open question for the design doc is whether the cheap structural cross-story check pays for itself, and it deserves its own artifact measurement (validator hit rate) rather than either anecdote.
- **PROCESS_GUIDE injection.** "Nearly never" used; agents follow the skill text in front of them.
- **The event-type taxonomy at current granularity.** 16 types with per-type required fields; in practice legacy's log is 61% `status`+`commit` (auto-generated), and the high-value content concentrates in `decision`/`concern`. The status-event firehose (499 in legacy) feeds conflict detection that worktrees mostly obviate.
- **Meta-test mass.** 191k lines of tests guarding 52k lines of hook plumbing is the simplicity violation in one ratio. Cutting the plumbing cuts its test burden with it.
- **Incident-reference prose.** Skill text accreted through 388 releases now carries scar tissue ("sprint-103's 3-spawn fan-out had irreducible coordination races…") that newer models don't need and that new sessions can't ground.

## 5. Why the weight accumulated (so the successor resists it)

1. **Every incident became prose or a gate.** The retro→concern→fix loop worked *too* well on the plugin itself: each edge case became a paragraph, an escape flag, or a validator. Nothing had a removal path. The successor needs a deletion bias: every added rule must displace one.
2. **Enforcement was built for weaker models.** Much of the hook mass encodes distrust that 2026 models no longer earn at the same rate (per Paul, and per testimony: red-first, commit hygiene, gate-before-done are now "would do reliably unaided"). The two exceptions with evidence: **fault injection** and **honest scope statements** — keep enforcement exactly there.
3. **Bookkeeping was mistaken for communication.** The SMM's broadcast idea is sound, but most event traffic is telemetry no one reads back. The load-bearing subset is small: constraints, open concerns with falsifiers, the current plan.
4. **Process managed process.** Adoption ledgers for retro items, force-close gates for deferrals, caps with retire-protocols for principles — three levels of meta. None of it changed the TDD-gap trendline.

## 6. Testimony from agents working under the plugin

Two active sessions were asked for critical assessments; both replied in depth. They agree on the core (fresh-context review is the mechanism; executable ACs are what keep "done" honest; pillars/retro/budgets are the weight) and disagree instructively on file_domain.

**Evidence weighting (read this first).** Testimony from running agents carries recency bias: sessions have little memory of prior sessions, so whatever an agent hit *this* session registers as bigger than its base rate — a gate that misfired once today outranks a gate that has silently done its job for a month. Accordingly, every testimony claim below was checked against artifacts (code, event logs, hook-error logs, sprint archives, retro files), which don't have this bias, and the audit's verdicts rest on the artifact evidence with testimony as color:

| Testimony claim | Artifact check | Standing |
|---|---|---|
| Reviewer/fault-injection catches are real and self-review can't replace them | Retro Keep items cite event ids; git history full of caught-defect commits (story-011 false green, story-021 audit) | **Corroborated** |
| Budget friction is chronic | `hook_errors.jsonl` across 5 projects: 141 budget-rejected writes on 15–17 distinct days/project over a month — longitudinal, not one bad day. (Cuts both ways: it also proves the caps were binding on real wordiness) | **Corroborated, reframed** |
| Retro+housekeeper are a heavy kickoff tax | Structural: xp-kickoff mandates both as *blocking foreground* subagents every session ("Kickoff is not complete until housekeeping finishes"); retro Fix items repeat unfixed across sessions. The ~115k-token figure itself is one measurement | **Mechanism corroborated; magnitude single-sample** |
| Debt/concern triage fails | Unresolved counts, sprint story-count growth, divineruin's 194/199 cull — all artifact | **Corroborated** |
| Lint hook is a "bug-shaped trap" | Code shows staged-bytes linting is deliberate and correct; the trap was agent error | **Refuted** |
| Pillar items mostly unread (~3 of 35), PROCESS_GUIDE unconsulted | Unverifiable from artifacts (reads leave no trace). Weak corroboration: PROCESS_GUIDE demonstrably duplicates skill text | **Testimony-only** |
| file_domain collision validator is high-value / file_domain is post-hoc paperwork | Both directions single-session anecdotes; artifacts show the validator exists and fires, not its hit rate | **Testimony-only, both sides** |

**Session `audit-vacuous-guards-class`** (closed legacy sprint-050 end-to-end: 3 stories, 2 plan reviews, 3 close reviews, ~40 gate interactions) — self-aware caveat that it's "the agent being asked which of its constraints to remove," so it weighted evidence over preference:

- Keep 3: (1) the independent reviewer with adversarial framing, (2) executable acceptance + verify-touch, (3) fault injection as a reviewer-enforced constraint.
- Drop first: content budgets; close-pipeline prose (→ a script that stops at the review); file_domain; every SMM pillar except Constraints.
- Would do right unaided: red-first, commit hygiene, gate-before-done, no lint suppression. Would *not*: fault injection (7 self-shipped vacuous guards prove it) and honest scope statements ("the reviewer forced 'this story closes zero of the 16 evidence ids' into a doc where I'd first written 'one'").
- The closing principle: *"If a mechanism can't fail — can't tell you something you didn't already believe — it's the same defect story-021 spent a whole story auditing, one level up."*

**Session `wire-e2e-typecheck-gate`** (mid-sprint on divineruin, sprint-044: kickoff done, one teammate spawned, second story planned):

- Highest value this session: fresh-agent **plan review**, which caught two *artifact-coherence* failures it would have shipped — a file_domain omitting ~13 files the plan actually edits (while listing 8 inert ones), and a story acceptance command naming a test file the plan deletes (the gate would exit 4 and prove nothing post-landing).
- Rates the **file_domain collision validator** "the best cost/value ratio in the whole system" — a CLI refusal naming both owners revealed planned work was already homed in another story. (Contrast with §4's DROP on file_domain-as-lane: the resolution is to keep the cheap structural *cross-story* check and drop the per-agent lane policing.)
- Measured kickoff overhead: **~115k subagent tokens** (retro + housekeeper) before any work; ~10 triage questions to the user of which several were mechanically determined by earlier answers.
- Injected-context usage: **~3 of ~35 pillar items**; Risks zero; PROCESS_GUIDE unconsulted ("a third copy after the skill text and my defaults"). By contrast, the file-based memory system was used repeatedly and unprompted — *"specific beats general for recall"* (memories are situational; pillar constraints are abstract).
- Keep 3: fresh plan review; file_domain declaration + collision/coverage validation; executable ACs on the story. Drop first: the four-pillar SMM + housekeeper ("if you keep any of it, keep a hand-maintained 10-line constraints file the human edits"). Drop second: the retro agent — the LAST_SESSION block "delivers most of the value at ~2% of the cost."
- Would not do unaided: **writing down a decision and its reasoning at the moment it's made.** But "a single `note <text>` append with no schema would capture 90%" of what the taxonomy+budgets apparatus buys.
- Sequential-discipline verdict: keep exactly one rule (never batch AskUserQuestion with the action consuming its answer); drop the rest.
- One hook it would keep, having watched it fire correctly: the exit-status-masking block (`… | tail -5; echo $?` makes the exit status the wrapper's) — "a real class of self-deception, and the message explained the fix precisely."
- Structural observation: *"the highest-value catches this session were all artifact-coherence failures — plan vs story record, story record vs acceptance command, new story vs existing story's domain. Aim the survivor mechanisms at keeping the small number of durable artifacts consistent with each other, and let code quality ride on tests plus a review agent."*

## 7. Design constraints carried into the design doc

From Paul, explicit:

1. Dual-CLI: Claude Code **and** Codex, including cross-CLI subagent launches for real separation (xp-agents already ships a Codex manifest + hook config; subagent launching is in-flight there).
2. 80–90% less prose and code, same spirit.
3. Consistent lane-keeping (trust comes from the process being followed every time) — but lighter-handed.
4. Better debt triage than both the pile-up and naive now-or-never ("now" over-selected by agents lacking deadline pressure).
5. Test economy: deliberate tiers for what runs when (per-commit / story-close / sprint-close), catching things early without paying full-suite latency on every increment.
6. Shared knowledge across sessions is worth something, but only at a token cost that stays honest.

Emerging from the evidence, proposed as the successor's razor:

> **Keep every mechanism that creates independent adversarial pressure on the work, and every cheap structural check that keeps the durable artifacts consistent with each other. Delete every mechanism that creates bookkeeping about the work. For anything in between, prefer one script over fifteen prose steps, one file over one taxonomy, and a falsifier over a tracker.**

## 8. Open questions for the design doc

1. **Enforcement floor.** Which gates stay *deterministic hooks* (unarguable, every time) vs. move to reviewer judgment? Candidate floor: tests-green-to-merge, plan-reviewed-before-execute, secrets scan, red-observed-before-green (light form). Is that floor enough for lane-trust?
2. **Falsifier-based concerns.** Format and enforcement point — at creation (append refuses concerns without a `resolved_when` command?) or at review? What's the auto-archive age?
3. **State surface.** Can the whole SMM collapse to: `plan.md` (execution plan + sprint), `constraints.md` (short, human-editable), `concerns.md` (falsifier-bearing, auto-archiving), a free-form decision journal (`note <text>`, no schema, no budgets), and a `LAST_SESSION` note — plain markdown in-repo, no event log, no CLIs? What's genuinely lost (conflict detection? cross-worktree broadcast?) and does worktree isolation + git already cover it? Related: testimony says *specific-and-situational* memory gets recalled while *general-and-abstract* pillar items don't — should cross-session learning ride on the host's native memory mechanisms instead of a curated store?
4. **Dual-CLI architecture.** Skills-as-markdown ports cleanly; hooks differ per host. Is the right shape "shared skill/agent prose + thin per-host hook adapters + one shared state dir," and what's the minimum hook set Codex can express today?
5. **Retro replacement.** If the learning loop must end in something executable, is the retro just: "propose a diff to the gates/constraints file, reviewed like any other diff"? (Process improvement as PR, not as ledger.)
6. **Test tiers.** Who declares the tiers (system context lite), and does story-close run the narrowed set with sprint-close running the full suite — or is even that too heavy?
7. **Teammate model/effort selection.** Can the 6-branch tier table become one sentence of guidance to the lead agent ("pick the cheapest model you'd trust with this story; say why in the spawn prompt")?
8. **Declarative-not-budgeted state writes.** Design the record shapes so that necessary-and-sufficient is enforced by *structure* rather than character counts (concern = claim + falsifier; decision = choice + because; status = file list). Which records genuinely need a free-text field at all, and for those, is truncate-with-notice acceptable?

## 9. The field walk — someone else ran it (Milestone 3's done-condition)

Milestone 3 asked for a consuming project to run a full story end to end under a
released version and report the result, "checkable by someone who is not us."
**It happened, and it went further than the card asked: Legacy ran a whole
sprint** — sprint-052, six stories plus the sprint close — reporting throughout.
Paul's judgment on it, 2026-08-26: "it worked."

VERSIONS: mixed, across 0.6.2 and 0.7.x — three in one day at the end. The exact
numbers were NOT read from their `env.json`, which the card originally required
(constraint 14's instrument, from the v0.6.0 failure where a consuming project ran
"0.3.0" while we recorded otherwise). Paul waived it: a walk spanning three
versions cannot be the single-stale-copy failure that AC guarded. Recorded at note
54da21bc — **this section is not evidence that constraint 14's instrument was
exercised.** It was not.

WHAT THE WALK FOUND, each filed as its own record with their evidence:

| leg | finding |
|---|---|
| story-001 | the 3600s wall clock killed a productive reviewer and discarded its round; the refusal named the bound, never `XP_AGENT_TIMEOUT`, the knob that moves it |
| story-002 | a codex story-reviewer whose sandbox denied Docker could not run Verify — and reported the round non-blocking anyway |
| story-004 | the profile-size warning blamed the project for a file the plugin generates; `plan_review` exited 2 having already written its round file |
| story-005 | disposition matched each findings reason VERBATIM against hard-wrapped prose: 0 of 7 verbatim, 7 of 7 normalized. A good review reported as one that never ran |
| story-006 | three defects from one dependency, each invisible in-process — four times bun+tsc green with the native build dead |
| close | `sprint_close.py` exited 0 having done nothing when invoked directly, which is how a falsifier batch reports as passed without running |

Fixed and released since: the codex plan-review timeout (v0.6.4), disposition's
verbatim match (v0.7.3), sprint_close's silent exit and the one-execution-per-record
batch (both v0.7.5). The rest remain open records; one became story-036.

**The verdict: Milestone 3 is met.** Not because the walk was clean — it was not —
but because the deliverable was always the measurement. Every defect above was
invisible from inside this repo and obvious from outside it, which is the thesis
the milestone states.

**The caveat, which no amount of walking fixes retroactively:** the fixes above
landed AFTER the walk that found them. No released version has been walked
end to end with those fixes in it. That is Milestone 4's problem, not evidence
against this one.

## 10. Sprint 8 — the Codex lead walk

Sprint 8 was led through the real repository by Codex, from card review through
four story lands, sprint close, release PR, merge and post-merge. This section's
authoritative transcript is `~/.codex/sessions/2026/08/26/rollout-2026-08-26T16-36-17-01a0406e-7bdd-7cb1-85c2-5635e9e0257f.jsonl`, abbreviated **R** below; citations give its UTC timestamp and, where useful, its JSONL line. The other records are `<data-root>/work.md`, `<data-root>/archive.md`, `<data-root>/logs/`, `<data-root>/closes.jsonl`, `<data-root>/markers/sprint/8.json`, and git range `fce14be~1..d473198`.

### What was and was not read

- **READ:** all 22 real user turns and the assistant responses answering them;
  all 13 developer messages; all 31 notes and the one bug filed during the
  session window; and all 32 commit bodies in `fce14be~1..d473198`. The three
  user-role `<environment_context>` injections were counted but are not user
  turns. The work-file window also held 15 resolved and 123 archived disposition
  blocks; 58 further blocks had been compacted into `archive.md`. Those counts
  are not relabelled as 31 decisions.
- **READ:** every one of the 13 output neighbourhoods containing `Traceback`, all
  66 containing `refused:`, all 47 direct `apply_patch` calls, all 11
  `update_plan` calls, all three web calls, and the seven native wait calls.
- **COUNTED, NOT READ:** 1,092 custom calls, all named outer `exec`. Their nested
  invocations overlap: 445 `exec_command`, 608 `write_stdin`, 47 `apply_patch`,
  11 `update_plan`, and three web calls. The card's substring command totals are
  therefore an index, not a partition of work performed.
- **SAMPLED:** first, midpoint and last calls from the remaining deterministic
  substring pools: inspection (179 candidates), git (87), story review (15),
  story land (8), sprint close (20), plus the sole literal `spawn.py resume`.
  The samples crossed kickoff, story work, close and release; no random or
  favourable sample was substituted.

Five compaction records replaced the model's active history at **R** lines 1008,
1893, 4041, 5639 and 6319. They did not delete the preceding JSONL records, so
the file supports this audit even where the live lead no longer held the earlier
turns. Six developer messages — every SessionStart profile of the session — were
themselves cut by Codex at **R** lines 9, 1013, 1898, 4046, 5644 and 6324, and
the cut is deterministic: a 4,944-char head and a ~5,050-char tail around an
inline `…N tokens truncated…` marker, ~10,000 chars total, identical in all six.
THE BOUND IS IN TOKENS, not bytes, and the marker is what says so: `original -
truncated` is **2,458 exactly** in all six (4,159−1,701 · 3,978−1,520 · 4,032−1,574
· 4,132−1,674 · 3,766−1,308 · 3,780−1,322), holding across three different tail
contents where a byte rule would have varied. Those 2,458 tokens carried 9,912
chars of this repo's markdown — 4.03 chars/token, and its own tool outputs
measure a 3.98 median — so the character figure below is a PROXY for the bound,
not the bound.
So it takes the MIDDLE, not the tail: each one still ends
`--- END project content ---`, and each is headed `Warning: truncated output`
with a path to the full text on disk. What the lead lost was PROCESS from its
`Debt triage` line onward, the recovery block, constraints 1 through 7 whole and
constraint 8's heading — announced as a token count and named as nothing. Unlike compaction, that loss
reached the transcript already cut.

### Hand-steps and control-flow substitutions

This table is exhaustive for material interventions found in the read sets.
Status questions that changed no state were read but are not hand-steps.

| step | evidence and disposition |
|---|---|
| Repository guidance was missing at entry. Codex natively read `AGENTS.md`, found none, and began without `CLAUDE.md`; the lead then added a pointer. | Initial profile, **R** 2026-08-26T23:39:29Z; record `e1585048`; commit `0948926`. This was a repository integration gap, fixed during the sprint. |
| The human granted three command-prefix approvals and then changed the lead from the initial sandbox to danger-full access. | Developer messages at **R** 23:43:58Z (cached `spawn.py`), 01:12:25Z (`git commit`), 01:21:15Z (`close.py`), and the permissions injection at 01:23:14Z. These were Codex host-authority hand-steps, not pipeline work. |
| Card review required the lead to add missing `Verify:` lines to all four cards, then correct story-057's false `-k` premise and remint story-059 after its Verify/depth mismatch. | **R** direct edits 1–6; records `1713f853` and `4b8ad70b`. This is lead judgment the card-review step owns; it was not hidden automation. |
| The story-052 executor entered a nine-round plan-review loop. The human stopped it and asked the lead to work in its tree; the lead deleted the stale incomplete marker, wrote the implementation and tests, and committed the green change itself. | User turns at **R** 00:25:25Z and 00:28:38Z; direct edits 7–15; records `11d13714`, `0336fbab`, `7687b057`; commit `d798f73`. This is the clearest pipeline substitution: the lead became the executor. |
| The lead interrupted story-054 and story-059 reviews after attributing delay to machine contention. The human rejected that diagnosis, required each interrupted tree to be completed, replaced the 30-minute policy with unbounded waits, and later allowed two streams. The lead inspected and salvaged staged reviewer edits before relaunching. | User turns at **R** 01:29:32Z–02:31:24Z; records `6cf4f66b`, `9acbe026`, `89a19e70`, `8c864027`; story merge commits `de2b274`, `3f1d32e`, `a2a4acb`, `5e81116`. The correction was human; salvage and relaunch were lead hand-work forced by the interrupts. |
| The lead repeatedly rewrote `session.md` from current artifacts. | Direct-edit read, including calls 16–18 and the close/release edits; final cleanup commit `d473198`. This is the intended LLM-present digest judgment, not a missing script step. |
| Sprint close exposed a retired card as unfinished. The lead filed and fixed the defect, then moved deferred cards into Sprint 9 on the human's direction. | User turns at **R** 05:04:03Z and 05:05:33Z; bug `65a075f4`; fix `dea86ea`; direct edits 30–40. The defect was fixed in the audited sprint; regrouping remained lead plan judgment. |
| The human authorized the release merge and post-merge. The first post-merge attempt correctly refused off `main`; the lead changed branches and reran it. | User turn at **R** 15:58:01Z; refusal neighbourhood **R** line 6573; merge `835f7e2`; cleanup `d473198`. This was the explicit human release boundary and a working branch guard. |

The other material lead corrections are recorded rather than inferred: the
initial backup claim was false (`32d21ffd`), the cached-plugin path mattered
(`4c34a506`), story-054's concurrency and reviewer decisions are in `5cb6dcdc`,
`c4637e0d`, `ea1c1589`, `523fbfe1`, `f2c571ff`, and `a1990b2c`; story-057's
falsifier, timing and card corrections are in `1b3f8b35`, `a8dc210d`,
`63797df4`, `dd3a1d00`, and `168ab415`; story-059's launch/install boundary is
in `9bddb126`, `daf7dbf2`, `3109dab5`, `810c3fa0`, `67a59d53`, and `348304f3`.

### Codex-vs-Claude claims

| shipped claim | Sprint 8 result |
|---|---|
| Codex's PostToolUse/Stop path is inert. | **UNEXERCISED.** No `<session>.test-status` exists, but absence cannot distinguish a hook that ran and wrote nothing from one that never fired. The prior deterministic payload analysis still stands; this walk adds no positive trace. |
| Spawned Codex runs end without Claude's turns/cost/duration summary. | **CONFIRMED.** Complete handbacks after `[turn.completed]` carry only the story result and recovery instruction, with no in-band counters (**R** lines 832 and 843). Outer tool wall time is not a spawned-run summary. |
| Spawned Codex teammates load no hooks or skills. | **CORRECTED.** Native transcripts `01a04075-7d61-7a11-a539-19f1ba801006`, `01a04075-6629-7fa0-81ae-5f9fecb0806a`, `01a04075-816e-7f71-9a77-63c93c42c5f9`, and `01a04075-74c6-7a21-96f9-1e4894563a0b` each contain the installed xp-plugin skill catalog and the `xp-plugin 0.8.2 · teammate session` SessionStart marker. The inlined card/VALUES/constraints remain worktree authority because Codex has no `--plugin-dir`; installed hooks and commands can therefore disagree, as record `3109dab5` observed. |
| The lead SessionStart profile fits its declared transport. | **FALSIFIED AND FIXED.** The six cut developer messages above report original token counts of 4,159 / 3,978 / 4,032 / 4,132 / 3,766 / 3,780, so they are six profiles of ~14–15.5k chars, all beneath the plugin's former 18,000-char cap and all above Codex's; the 15,442-char figure on the bug is the profile measured at filing. Bug `d3685f4d`, resolved as `c85e6dce`, lowers the cap to 9,000 chars — under Codex's measured 2,458-token retention at any density above 3.7 chars/token. The 10,000 this section first proposed was ~2,480 tokens of our own markdown and would have been cut again, which is the same units error one layer down; caught at story review, and the test now pins the token figure and the conversion separately rather than a bare 10,000. `tests/test_session_start_profile.py::TestTheRealProfileAgainstTheRealCap::test_this_repos_profile_fits_with_values_and_process_leading_it` constructed the red and now pins it. |
| Codex needs explicit host authority where Claude's configured lead does not pause. | **CONFIRMED for the initial posture, then changed in-session.** The three approval messages and the 01:23:14Z permissions injection above are positive traces; no conclusion is drawn about hosts configured differently. |

No other leg difference was evidenced by the scoped read. In particular, the
four story-review/land sequences, sprint review, release and post-merge all
reached their shared artifact or commit contracts; that is not a claim that
unread tool-call interiors behaved identically.

### Tracebacks and refusals

All 13 `Traceback` neighbourhoods were read. Three were quoted source or record
text rather than exceptions (**R** 1637, 4201, 4476); three were intentional
`KeyboardInterrupt`s while stopping work (939, 1465, 1488); four came from bad
ad-hoc diagnostics (121 wrong helper id, 929 missing `__file__`, 4823 and 4829
wrong import roots); three were the initial sandbox denying the
data-root/SessionStart probe (155, 1066, 1084). None exposed a defect in the
shipped plugin.

ONE OF THEM EXPOSED A VACUOUS CHECK, which the shipped/not-shipped line above
does not cover and constraint 2 does. **R** 1066 is
`tests/scripts/falsifier_lead_profile_fits.py` dying on `ValueError: substring
not found`. The cause is not the sandbox: `run_hook` is advisory, so a hook that
raises exits 0 with its traceback on stderr and NOTHING on stdout, and that empty
string passes the falsifier's `"teammate session" not in out` guard — which
excludes one wrong state and admits the other (constraint 15). Reproduced here
against an unwritable `XP_DATA`: the falsifier reported the same `ValueError`,
and in `tests/test_session_start_profile.py` the two tests that early-return on
`"[truncated" not in out` PASSED on the empty profile — the exact vacuity that
file's own docstring exists to prevent. Both now assert the profile is non-empty.

Of 66 outputs containing `refused:`, 49 were source, log or report readbacks, not
fresh refusals. The 17 live/control outputs included repeated polls of the same
event. Sixteen show a wall or control doing its job: missing Verify, no-commit
escalation, test-gate red, reviewer-patch commit refusal, concurrency/overlap,
sprint membership, the intentionally red retired-card regression, falsifier
batch refusal, and the post-merge branch guard. One shows the lead fighting the
CLI: it supplied 77 record ids as one `--ref`, received zero matches, then
iterated them correctly (**R** line 4889). A count alone would have called all 66
friction; the neighbourhoods show one malformed invocation and the rest either
quoted evidence or working boundaries.

### What the fix for `d3685f4d` costs this repo

Stated because the fix is not free and the notice is the only thing that says so.
Under the old 18,000-char cap the Sprint-8 lead did reach constraints 9-15 whole,
the tail of 8, and the whole session digest, because Codex keeps the tail; it
lost PROCESS's own tail and constraints 1-7 in the middle, unnamed. Under the
9,000-char cap this repo's profile assembles 8,975 chars — about 2,230 tokens
against the measured 2,458, so Codex cuts nothing — and the lead
reaches ZERO of 15 constraints and no digest at all, with
`[truncated ... CONSTRAINTS 1..15 ARE NOT ABOVE]` naming every one. The trade is
Honesty over coverage: fewer rules delivered, none silently. It is loud, so it is
not a defect under the finding bar, but nothing else measures it — the falsifier
and `test_this_repos_profile_fits_...` both assert only that the profile FITS,
which lowering the cap can always make true by dropping more.

WHAT THIS DOES NOT DECIDE: the profile assembles the recovery block ahead of the
rules, and §8's stated ordering rationale — constraints before the digest,
because a digest is recreatable from git and work.md — applies word for word to
the recovery block, which is recreatable from the same two sources. Moving rules
ahead of it would deliver roughly seven of them here (measured at the 9,000-char
cap; it was ~eleven at the 10,000 this section first proposed). `test_recovery_block_
survives_the_cap` pins the current order, so that is a retro decision with a test
to retire, not a fix to smuggle into this card.

### Boundary and verdict

This was not a first run. The repository already had `.xp/` state and the user
installation already carried xp-plugin 0.8.2. Installation, trust, scaffolding,
and first SessionStart behavior in a never-configured repository remain
**UNCOVERED**; the live sprint is not evidence for them.

Within that boundary, the walk supports the Codex-lead design claim. It also
required a human to correct a false contention story, stop one runaway planning
loop, grant host authority and authorize release; the lead directly substituted
for one executor and salvaged two interrupted reviews. The reading found one new
defect, `d3685f4d`, in addition to the already-filed-and-fixed `65a075f4`, and
the story review of this section found a second in the same neighbourhood: the
empty-profile vacuity above, which is owed its own record. A walk
that produced those corrections is stronger evidence than a clean summary, and
the READ/COUNTED/SAMPLED split above states exactly where that evidence ends.
