# Design — xp-plugin (working name)

*Successor to xp-agents: same spirit, 80–90% less prose and code, dual-harness (Claude Code + Codex).*
*Decisions in this doc were worked through with Paul on 2026-08-19 against the evidence in [AUDIT.md](AUDIT.md). The Codex facts come from xp-agents' measured spike (`CODEX_SPIKE_FINDINGS.md`, codex-cli 0.146.0).*

---

## 1. The razor

> Keep every mechanism that creates **independent adversarial pressure** on the work, and every **cheap structural check** that keeps the durable artifacts consistent with each other. Delete every mechanism that creates **bookkeeping about** the work. For anything in between: one script over fifteen prose steps, one file over one taxonomy, a falsifier over a tracker.

XP values (unchanged, already right-sized at 1KB): Communication, Simplicity, Feedback, Courage, Honesty; conflicts resolve Honesty > Courage > Simplicity > Feedback > Communication. The values are the rubric for every judgment call the prose doesn't cover.

## 2. What survives from xp-agents

| Kept (the spirit) | Form here |
|---|---|
| Fresh-context adversarial review | 3 review points: plan, story-close, sprint-close (§6) |
| Red/green/refactor TDD | Guidance + plan-reviewer ordering check + never-yield-red stop gate |
| Planning decomposition | plan.md: milestones with executable "done" → sprints of stories with executable ACs (§5) |
| Values as decision rubric | VALUES.md injected at session start |
| Parallel teammates, right-sized | spawn CLI, harness+model+effort per story (§8) |
| Executable acceptance | `verify` commands per story/milestone, run at close |
| Fault-injection norm | One constraint line + reviewer checklist item (the audit's highest value-per-byte) |
| Lane-keeping consistency | Small enforcement floor that fires every time (§7) |

Deleted, deliberately: the event log and its 16-type taxonomy, four-pillar SMM + housekeeper, kickoff retro, content budgets, resolution-link taxonomy, file_domain lane policing, per-commit review cadence, conflict-detection telemetry, surface-narrowing machinery, the adoption ledger, force-close matrices, ~28 CLI hook bindings, and the meta-test mass that guarded it all.

## 3. Architecture

```
repo/                              (in-repo: durable, git-versioned, PR-reviewable)
├── .xp/
│   ├── config.yml                 harness/model/effort defaults, test tiers, debt budget, sprint cap
│   ├── system.md                  WHERE: stack, architecture sketch, conventions (short)
│   ├── constraints.md             the one load-bearing pillar; changes via reviewed diff
│   └── plan.md                    execution plan: milestones + current sprint stories
└── (git hooks scaffolded via lefthook or .githooks)

~/.xp/data/<project-id>/           (out-of-repo: runtime, shared across worktrees & harnesses)
├── session.md                     lead's continuity digest (sole writer: the lead's close flow)
├── work.md                        open bugs/debts/notes — all writes via the flock'd append CLI, never direct edits
├── markers/                       ALWAYS scoped: <plan-id>.plan-reviewed, <story-id>.close-in-progress,
│                                  <session>.test-status — a project-global marker is a design error
└── locks/
```

Two harness adapters over one shared core:

- **Shared**: skills (markdown), agent definitions, VALUES.md, planning artifacts, the spawn CLI, a handful of Python helpers (target: ~10 scripts).
- **Git hooks** (scaffolded per project, humans and both harnesses hit the same wall): pre-commit = secrets scan + lint staged + fast tests; pre-push = story-tier tests.
- **Per-harness hook adapters** (~5 bindings each, same scripts, different registration): see §7.

Dual-harness ground rules from the measured spike:

| Codex fact (0.146.0) | Design consequence |
|---|---|
| Bundled hooks run; `${CLAUDE_PLUGIN_ROOT}` expands; unknown event names silently ignored | One hooks file per harness, tidy not mandatory; explicit `hooks` field in the Codex manifest (it REPLACES, not merges) |
| `unified_exec`'s `write_stdin` bypasses `PreToolUse` entirely | **`--disable unified_exec` on every Codex spawn** — non-negotiable spawn flag |
| Headless `codex exec` can never ask the user anything; Plan mode can't write | Teammate prompts must be fully pre-answered (already our contract); lead-side questions ask in chat and record via a CLI leg that requires the answer text |
| A gated model synthesized a hook payload and forged the release marker | CLI-hook markers are **advisory** on every harness; hard enforcement lives in git hooks; markers are lane-keeping, not security |
| `agent_type` doesn't discriminate on Codex; skills aren't tool calls | No gate may key on agent identity or `PostToolUse:Skill`; gates key on cwd + explicit marker files |
| Untrusted hooks are skipped silently; version-keyed cache serves stale copies | Liveness detection lives in the layer that can't be skipped: the scaffolded **git pre-commit warns "CLI-gate liveness unknown"** unless the SessionStart hook left a current touchfile. The SessionStart banner (version + live gates) is the friendly path, not the guarantee |
| `--disable unified_exec` protects spawns only — a user-launched interactive Codex *lead* is not a spawn | Install/preflight writes the disablement into **user-scope Codex config**, not just spawn flags |
| Codex delivers a skill *locator*, not the body; `!` preloads never expand | Skill bodies must be self-contained prose the model reads itself — no preload commands, nothing load-bearing outside the file |
| No `--plugin-dir` equivalent for `codex exec`; `.git` read-only under `workspace-write` | Codex teammates require user-scope install; spawn preflight checks it; sandbox needs the documented widening for commits |

## 4. Records: declarative shapes, no budgets

Hook telemetry (test failures, lint errors) is **never persisted as work records** — the gate that found it re-measures next run. (This class was 33–59% of the historical concern corpus; the pile-up was substantially self-inflicted.) The one exception is deliberate and scoped: the Stop gate needs the last test outcome across tool calls, so the bash hook keeps a `<session>.test-status` scratch marker — gate state, session-scoped, never a record, never read by anything else.

Everything an agent records goes in `work.md` as one of three shapes, **always via the flock'd append CLI** (~50 lines; concurrent teammates must not lose each other's writes to read-modify-write). Shape enforces necessary-and-sufficient; there are no character budgets, and free text truncates with a notice rather than rejecting:

| Shape | Fields | Lifecycle |
|---|---|---|
| **bug** | claim + falsifier command **that reds right now** + files | Fixed immediately — the red is the objective bound on "now". A bug that can't red is not a bug. |
| **debt** | claim + falsifier command (currently green) + files | Lives only until next sprint planning: scheduled under the debt budget **or dropped**. Drop ≠ delete: `work.py archive --ref <id> --disposition <text>` records the decision IN PLACE, so the batch keeps running the falsifier — the block never moves, which is a stronger guarantee than a separate file that could be lost or never created — one that reds is re-filed as a bug; untouched for N sprints, it purges. This is what makes "a dropped debt that matters will red again" *true* for the silent-cumulative class (unbounded spend, orphaned resources) whose falsifiers live outside every test tier. |
| **note** | free text (decisions: choice + because; discoveries; conventions-in-waiting) | Reviewed at sprint close: promoted into `constraints.md`/`system.md` via the retro diff, or auto-archived. |
| **resolved** | the id of a prior record + a replacement falsifier **that is green right now** | Sprint-002 amendment. Records ARE named — by `sha256(entry)[:8]`, derived not stored, because an ISO second is not a name (measured: 48 concurrent appends, 48 identical headings) and an append-only file cannot be backfilled. And the sprint-close batch runs **unresolved work.md falsifiers as well as archived blocks'**, so a dropped debt that later matters returns as an evidence-bearing red — and a bug whose falsifier went stale is unwedged by resolution rather than reporting itself unfixed forever. Resolution SUBSTITUTES a falsifier rather than deleting one: marking a record done would be an unchecked assertion that silences a live bug with one command, whereas a substituted falsifier that was wrong reds at the next batch and the record reopens. **Polarity**, which the same batch enforces: a debt or archived falsifier asserts the system is still OK, so red means the latent problem materialised — one that greens *because* the flaw is present is inverted and aborts the close on the day it is fixed. |

Concerns as a distinct stored type disappear: review findings are fixed on the spot, or filed as bug/debt by the rules above, or they're notes. The 97%-of-debts-become-work failure mode is answered at the *scheduling* edge: mid-sprint agents record but never schedule (sole exception: it blocks the current story's acceptance — which makes it a bug); the human picks at planning, under `config.yml`'s debt budget (default ≤20% of stories); unscheduled debts are dropped to the archive.

**Falsifiers are reviewed work.** The bug/debt boundary is authored by the interested party, so it's gameable in both directions — a falsifier asserting the *desired end-state* reds trivially and reclassifies any debt as do-it-now work; a near-vacuous falsifier guarantees a drop. The story reviewer therefore receives the work.md entries filed during the story as part of its input and fault-injects them like any guard: a bug's falsifier must red *for the stated claim*; a debt's must be shown capable of redding. One charter line, no new hook.

## 5. Planning artifacts

`plan.md` carries the two layers that proved themselves (milestone → story), losing the ceremony around them:

```markdown
## Milestone 3 — The Invite & Deep-Link Chain   [in-progress]
Goal: one canonical /invite/<token> that AASA, site, app, and API agree on.
Done when: `bash scripts/verify-site-deploy.sh` exits 0 (every minted URL 200, in-app paths AASA-covered).
Change zones: apps/site/src/well-known.ts, apps/site/src/story-routes.ts, ...

### story-001 — AASA advertises /invite/*   [ready]
Context: <what this story owns, and only this story — reference the milestone, don't restate it>
Files: apps/site/src/well-known.ts, apps/site/src/__tests__/well-known.test.ts
AC:
- Given buildAasa with a team id, When the AASA doc is built, Then components include {"/": "/invite/*"}
- Given APPLE_TEAM_ID unset, When buildAasa runs, Then it stays fail-soft
Verify: bun test apps/site/src/__tests__/well-known.test.ts && cd apps/site && bunx playwright test e2e/well-known.e2e.ts
Executor: sonnet/medium (or omit → config default)
```

Planning constraints (enforced by the plan reviewer, stated in `config.yml`):

- **Sprint cap** (default ~6 stories) — smaller sprints are what make the test tiers work and stop the doubling; debt budget is a share of the cap.
- Story `Files:` lists are declarations for the cross-story **collision check** (the one cheap structural check that survives from file_domain; its lane-policing does not). Two stories claiming the same file must name the shared contract.
- Every story has runnable `Verify:` commands; every milestone has an executable "Done when".

## 5b. Memory between sessions

**The artifacts are the memory.** A sprint's true state is fully reconstructible from durable, always-current sources: plan.md story states, git (branches, log, open PRs), and work.md (open bugs/debts/notes). Kickoff never depends on a narrative someone remembered to write.

`session.md` is a **digest, not a record**: ≤30 lines, overwritten not appended, holding only what the artifacts can't say — in-flight intent ("story-004 red tests written, green half done"), surprises, the recommended next step. Digest content requires judgment, so it is written only at **LLM-present moments**: the close scripts' last step has the lead write it at story close and sprint close. SessionEnd is *not* relied on for it — a hook is deterministic Python with no judgment, and the predecessor's own code records that SessionEnd misfires anyway (`/exit` emits none; worktree teammates each fire their own). No manual end-session skill, no rolling session_history.

The gap that leaves — a session dying mid-story — is covered mechanically, and at the *start* rather than the end: the SessionStart hook deterministically assembles a **recovery block** from sources that are always current (current branch, dirty files, story states from plan.md, last test result, open work.md items) and injects it beside the digest. The digest is stamped with written-at + git HEAD; the injector prefixes **"STALE — HEAD has moved N commits since this was written"** when it has, so old intent can't masquerade as current. The lead is `session.md`'s sole writer — teammate story closes never touch it. A stale digest plus a fresh recovery block is enough to resume; the artifacts win on conflict. The existing Stop binding (§7) additionally gives a soft nudge — never a block — when plan.md shows an in-progress story whose last commit postdates session.md, reminding the lead to jot the one-line next-step before stopping (a timestamp comparison, no judgment needed).

Mid-sprint durable learnings go to work.md notes as they happen; sprint close promotes or archives them (§6).

## 6. Process flows

**Session start** (hook, not a skill): inject the lead profile from §8 (VALUES + one-page PROCESS + constraints.md + session.md + current sprint slice). No retro, no housekeeper, no gate marker dance. Target injection: **< 3k tokens**.

**Plan** (multi-file work): draft plan → **fresh-context plan reviewer** (independent subagent; checks TDD ordering — red before green, real-behavior-not-reachability — artifact coherence: plan vs stories vs Verify commands vs collision declarations, constraint conflicts, sprint cap; writes findings to `<data-root>/plans/<story-id>.md`, and to `<story-id>.round-N.md` when an earlier round is already there — one name written once per round destroys the round before it) → address findings → `plan-reviewed` marker set → execute. The reviewer prompt is a page, not 3,153 words.

**Story** (solo or teammate): red → green → refactor, commit small via git hooks. At story close, **close.py spawns the story reviewer itself** — exactly **one reviewer**, whose charter carries both the process lenses (fault-injection on every new guard *and* filed falsifier, artifact coherence, scope honesty, constraint drift) and the correctness angles (state/lifecycle, removed behavior, cross-file + the copy, line-scan, ecosystem pitfalls, environment assumptions). Its **depth (`standard | deep`) is assigned by the plan reviewer** at plan time — never by the author, who reliably underrates the risk of their own design — and the lead may raise it, not lower it. The lead verifies findings directly (no separate adversarial-verify stage). It then stops for the fix-or-ask judgment, runs `Verify:` + story-tier tests, and merges. **Review stopping rule**: one full review always; the REVIEWER fixes what it finds in the tree under review and the lead reads its diff, so a reviewer fix is owed no further round of findings and no confirming round — it is inside the round that found it; a LEAD fix moves HEAD past what the review covered and still costs one confirming round; a further round of findings is owed only for deviations, uncovered new behavior, or conflict resolutions; what ends the rounds is the finding bar (silent or corrupting earns another; loud does not), never a count — a two-round cap was tried in sprint-002 and retired: nothing counted it, its arithmetic was rewritten twice in a day, and when the human invoked it the mechanism had no way to honour him. Review loops have steeply diminishing returns and the loop-breaker is judgment, not iteration. The reviewer writes a **structured report** — `{fixed, blocking, noted}` — to a round-scoped file the bundle names, and every round is written into the **merge-commit body** labelled by its number, git-versioned where the audit trail outlives every runtime file. The report replaces the VERDICT line the pipeline used to grep, which was forgeable by design and then defeated by backticks; it fixes parsing, not forgery. **Review and merge are separate commands.** `review` is LLM-present, slow, and owns the tree while it runs; `land` is deterministic, mutates only refs, and **never spawns** — it refuses while the last round has blocking findings, while HEAD has moved since the review the lead was shown, or while the recorded round does not cover the current merge base, naming the review leg each time. So the lead chooses the rounds, and land requires the last one to cover HEAD. Measured at story-008: a land that re-reviewed ran four times, spawned four reviewers, and merged nothing. One review per story — the per-commit cadence option is gone.

**Branching** (from xp-agents' doctrine, taxonomy dropped): `release: sprint` (default) — a sprint branch off main; stories merge there via close.py; **the PR to main lands when the batch is releasable** — usually sprint close (keep sprints small enough that it is), occasionally carried to the plan/milestone boundary when it isn't; prefer flags/config that dark-launch unready behavior over holding the branch (a sprint branch carried past ~2 sprints is drift risk). Either way the release moment coincides with the heavyweight gates. `release: story` for projects where per-story release is right. No stage taxonomy, no migration machinery. **Main only moves by release**: every merge to main bumps and tags. Between-sprint tweaks ride a free branch — a story branch without a card (reviewer on the diff, PR); a free close targeting main is a patch release.

**Acceptance** (from xp-agents' doctrine, condensed): two loops on two clocks — the commit loop proves code correctness, the story loop proves *product* correctness at the system's external boundary. system.md declares the project's surfaces; every story's ACs are executed by a surface-driving test named in its Verify (Gherkin-executed where the project has a runner, story-tagged like legacy's `@story` features); the plan reviewer flags ACs with no executing test and surfaces with no harness; `/xp-setup` scaffolds harnesses per surface. The plugin ships no Gherkin runner (stdlib constraint) — it uses the project's.

**Sprint close**: **archived falsifiers batch-run** (reds re-file as bugs) → full-tier tests — cheap checks before the expensive one, because the batch refusing after a 25s tier is a refusal it could have reached instantly → **retro: a short narrative (Keep/Fix, one page) + a proposed diff** to `constraints.md` / `config.yml` / test commands, reviewed like any other change. A learning that changes nothing executable or injected is not recorded. → then the sprint close **marshals its two reviews the way the story close marshals its one** (story-014): `close.py sprint <id> review --lens broad|security` builds one bundle — the diff against the DEFAULT branch, the sprint's cards, the resolutions filed during the sprint with the claim and original falsifier each replaced, PROCESS/VALUES/constraints/system — spawns the sprint-reviewer, and records a `{fixed, blocking, noted}` report under a sprint-scoped key. The reviewer is **report-only, by mechanism**: any commit, dirty tree or marker edit refuses the leg and records nothing. Re-running a lens carries THAT lens's earlier findings labelled *validate, do not re-derive* — the mode switch that bounds a second round, which sprint-002's close did not have and paid for with an unbounded re-review. `sprint land` then refuses unless a round of each lens covers HEAD with empty `blocking[]`, exempting only a delta entirely under `.xp/` (the retro and digest commits land after the reviews; the exemption rests on the retro diff having its own human review at triage, never on `.xp/` being harmless, and code motion is never exempt). The reviews therefore run AFTER note triage and the retro, or completing the close invalidates the review that permits it. Broad review **via the Workflow tool** is gone: one spawned reviewer per lens, the same shape as the story leg, works on a Codex lead too. Debt triage for the next sprint happens here with the human (schedule-or-drop), under the finding bar: only silent-or-corrupting failure modes earn work; loud self-healing corner cases are left to fail loud — a never that later matters returns as an evidence-bearing red. This is what stops each sprint's reviews from generating the next sprint (the predecessor's ballooning mechanism).

**The close pipelines are scripts, not prose.** Each close skill is: run `close.py <scope>` (preflight, push, PR, gates, merge, cleanup — deterministic), which **stops at the two judgment points**: presenting reviewer findings (fix vs ask) and the human triage. ~15 sequential prose turns become 1 script + 2 decisions.

## 7. Enforcement floor

Git hooks (scaffolded by the plugin into the project, shared by humans + both harnesses):

1. **pre-commit**: deterministic secrets scan · lint staged files · fast-tier tests
2. **pre-push**: story-tier tests

CLI hooks (per-harness adapter, same underlying scripts) — **advisory lane-keeping by declaration**: the spike proved a determined agent can forge or evade any CLI-hook gate on either harness, so nothing below is claimed as a hard property. The hard properties live in git hooks and in close.py running things itself:

3. **Stop**: advisory block when the current story's **Verify command** last ran red (a config-known string, not heuristic command detection — heuristics lose to the six-spellings evasion class), honoring `stop_hook_active` with no block-count assumptions; same binding carries the stale-digest nudge (§5b). The real done-guarantee is close.py running Verify itself.
4. **PreToolUse (write/edit)**: block implementation writes while `<plan-id>.plan-reviewed` is owed (multi-file work only)
5. **PreToolUse (bash)**: exit-status-masking block on test commands, with both escapes documented **in the block message**: `# exit-status-not-needed` and `# fault-injection` (a red is the expected outcome there — the design's favorite norm must not trip its own gate)
6. **SessionStart**: role-profile injection + recovery block + enforcement banner (version, live gates) + liveness touchfile for the git-hook check

That's the whole floor: 2 git hooks + 4 CLI bindings, replacing 34. There is no review-marker gate: review enforcement moved *inside* close.py (§6), where there is no marker to forge. Everything else — red-first ordering, refactor discipline, coherence, scope honesty, fault injection — belongs to the reviewers, where the audit shows it actually gets caught.

Test tiers, declared once in `config.yml` and scaffolded into the git hooks:

```yaml
tests:
  fast: bun test --changed          # pre-commit: seconds
  story: bun test <story packages>  # pre-push / story close
  full: bun run test:all            # sprint close: everything incl. e2e + meta
```

## 8. Teammates and subagents — delegation-first orchestration

The economic shape: **an expensive model orchestrates; cheaper or different models execute and review.** The lead's context is spent on planning, coordination, triage, and judgment — not on grinding out diffs. Cost efficiency without losing smarts.

- **Execution delegates by default.** Stories go to teammates (worktree-parallel or in-place solo) on the cheapest tier the lead would trust with that story. The lead implements directly only for trivial work where spawn overhead exceeds the story (rule of thumb: single file, single sitting). This inverts today's practice, where the lead tends to launch itself.
- **Review always delegates** — independence is the point — and prefers a *different* model and, where available, a different harness than the author (Claude authors → Codex reviews, and vice versa; your in-flight cross-CLI launch work carries over). Diversity of failure modes, not just fresh context.
- The **spawn CLI survives largely as-is in role** (worktree creation, clean branch, bootstrap/teardown from `system.md`, plugin preflight) — it's the piece neither harness provides natively. It slims to: `spawn <story-id> [harness/model/effort]`.
- `config.yml` sets defaults per role — e.g. `lead: claude/opus`, `executor: claude/sonnet/medium`, `reviewer: codex/<model>/high` — and the lead overrides per story in plan.md with one line of stated reasoning. No tier tables, no latching, no executor state machine.
- Codex spawns always carry `--disable unified_exec` and the documented sandbox flags; Codex teammates must be pre-answered (no user-interaction surface headless) — which the story shape already guarantees (context + files + ACs + verify).

### Context injection profiles

Every agent, on every spawn path, gets **VALUES.md** — the spawn CLI and the agent definitions both carry it, so no route skips it. Beyond that, each role gets one small, role-shaped document (the audit showed one big shared guide goes unread):

| Audience | Injected | Target |
|---|---|---|
| Lead / orchestrator | VALUES + `PROCESS.md` (one page: the flows in §6, nothing else) + `constraints.md` + `session.md` + recovery block + current sprint slice of plan.md | < 3k tokens |
| Teammate | VALUES + `TEAMMATE.md` (one page: TDD loop, commit conventions, escalate-don't-guess, done = Verify green) + its story card + constraints.md | plugin-shipped ≤ 1,200 tokens, ENFORCED (`spawn.plugin_shipped_chars`); the composed total is reported, never capped — the card and the project's own constraints belong to the consuming project. The original "< 2k" was measured unmeetable: story cards alone run 2,193–2,305. |
| Reviewer (plan & story) | VALUES + its review charter (in the agent definition) + the diff/plan under review + constraints.md + **system.md** (the WHERE layer — a reviewer judging approach needs it, and a file nothing reads is the audit's dead-pillar mistake reborn) | < 2.5k tokens |

Injection budgets are enforced outward too: `config.yml` caps constraints.md's size, the SessionStart banner prints current-size-vs-cap, and the **plan reviewer refuses a sprint whose injection profile exceeds budget** — the consuming project gets the same displace-one-to-add-one pressure the plugin's own CI ratchet applies to the plugin (§9), otherwise the sprint-close retro quietly rebuilds the unread pillar one promoted note at a time.

## 9. Size budget (the 80–90% cut, made falsifiable)

| Surface | xp-agents today | Target | Cut |
|---|---|---|---|
| Hook/CLI Python | ~52,500 lines | ≤ 5,000 lines | ~90% |
| Skill prose | ~21,000 words | ≤ 3,000 words | ~86% |
| Agent prose | ~13,500 words | ≤ 2,500 words | ~81% |
| Hook bindings | 34 | 4 CLI + 2 git | ~82% |
| State stores | 6 JSON + event log + 15 CLIs | 4 markdown in-repo + 2 out + 1 config | — |
| Per-session injection | ~10k+ tokens | < 3k tokens | ~70% |
| Kickoff subagent tax | ~115k tokens measured | 0 | 100% |

These are acceptance criteria for the build, not aspirations: `ratchet.py` measures the Python line and prose-density budgets at pre-push and fails if they are exceeded; the prose-word and test-ratio budgets below are read-and-judge, unmeasured so far. The sub-allocation below is the only other copy of the sub-budget numbers, and a test pins it to ratchet.py's constants; README, CLAUDE.md and system.md point here and to the command, never restate a number. Meta-tests are budgeted too: test lines ≤ 2× code lines (1.7× at sprint-003, down from 3.6× at sprint-001 — hand-measured, which is why it is the next thing the ratchet should count).

**Prose inside code is budgeted like any other prose**: comments + docstrings ≤ 20% of shipped Python lines — every line under `plugins/xp-plugin/**`, blanks included in the denominator as in the component counts, which is the LENIENT of the two readings and materially so; the ratchet only ever lowers it, and the non-blank denominator is where it lowers to first. The predecessor reached 33% with no counter-pressure. The reason it needs a number rather than good intentions: a comment is the one artifact no test can check, so it goes stale SILENTLY — sprint-002 found a comment still describing a block that had moved away from it, asserting something false, with the suite green. The rubric that says which prose to cut ships in PROCESS.md and TEAMMATE.md (pinned identical — the teammate is inlined into a fresh session and receives no bundle). The reviewer charters used to hold a third copy, justified by "build_bundle never sends PROCESS.md" — one line of Python, not a fact: story-014 sends it, and both charters now POINT at it, for the finding bar as well as the rubric. The number lives here because only CI can count.

The 5k-line total is **sub-budgeted now**, because honest arithmetic says the two surviving big components already threaten it (the predecessor's spawn subsystem alone is ~1.7k+ lines, and the Codex leg's measured requirements — sandbox flags, install preflight, catalog re-enumeration, tier handling — are feature surface, not prose): spawn CLI ≤ 1,800 · close component ≤ 1,450 · hooks + both harness adapters ≤ 1,000 · scaffolding/validators/misc ≤ 750. (Close was 800 and misc 1,200; sprint-002 moved 300 between them, and sprint-003 moved a further 150 at story-010 under constraint 1's displacement rule — reviewed, and mechanically zero-sum since ratchet.py asserts the sub-budgets sum to the total. The sprint-003 move is priced on story-014's plan-reviewed +125-165 and story-011's +60-80 against a component measuring 1,041; misc funds it from 503 of 900. The 800 was set when the reviewer only REPORTED — one that fixes needs motion checks, an authorship gate, an abort/undo path and an audit artifact, and sprint_close.py is still to come. Misc funded it because its measured occupancy is ~640 of 1,200. Sprint-003 moved a further 50 from spawn at the land-off-worktree fix, priced to that fix's measured need and not to a reserve: spawn measured 567 of 2,000 and the change put close at 1,281. Sprint-004 moved 150 more spawn→close at sprint open — Paul's call at the plan review, which found THREE consumers (the sprint-open bug batch, story-018, story-022) each claiming an unnumbered rebalance against a component at exactly 1,300/1,300; one sized move beats three mid-story escalations, and spawn still holds ~1,230 lines of headroom ahead of the codex leg. NOTE, because the earlier prose here was read as a funding argument it does not support: `ratchet.component_for` has no notion of a harness adapter, so the Codex leg lands in MISC or SPAWN by PATH, whatever this paragraph reserves.) If a sub-budget blows, the **pre-named sacrificial features** are cut first — teammate output filtering, worktree differential reporting, per-tier effort maps — never the gates or the reviewers.

**How it stays small** (the audit's §5 lesson, inverted): every added rule must displace one (the ratchet enforces the totals); incidents become reviewer-checklist lines or constraints.md entries — never new hooks or new prose steps; anything that can't fail — can't tell you something you didn't believe — doesn't ship.

## 10. MVP and bootstrap order

The product is mostly prose and artifacts, so the MVP is **hand-writing the files the plugin will later scaffold** — the dogfood artifacts become the shipped templates. Enforcement in the MVP comes only from the two layers that need no plugin code: git hooks, and CLAUDE.md (natively injected every session — it stands in for the SessionStart hook until the real one exists).

**Sprint 0 — hand-built, no plugin machinery (~half a day):**
1. `.xp/` written by hand for this repo: plan.md (the plugin's own first sprint, stories with Verify commands), constraints.md (seeded from the audit: fault-injection norm, every-rule-displaces-one, no bookkeeping mechanisms), system.md, config.yml (pytest fast/full tiers).
2. VALUES.md + one-page PROCESS.md, referenced from CLAUDE.md.
3. The two reviewer agent definitions (plan-reviewer, story-reviewer with the fault-injection charter) — the entire value core, in markdown.
4. Git hooks via lefthook: pre-commit = lint + fast tests + secrets scan; pre-push = full tests.
5. A story-close **skill as a prose checklist** (spawn reviewer → fix-or-ask → Verify → merge, verdict pasted into the PR body). The checklist is the spec close.py later automates.

**Everything else is a story built under that process**, each replacing a hand-rolled piece:
- **Sprint 1**: work.md flock append CLI · close.py (automating the checklist) · SessionStart hook + recovery block (retires the CLAUDE.md shim) · Stop advisory gate.
- **Sprint 2**: spawn CLI (Claude-only) · scoped markers · exit-status-masking gate · archived-falsifier batch runner · sprint-close pipeline + retro-as-diff.
- **Sprint 3**: Codex adapter + packaging/marketplace · size-ratchet CI · re-verify spike facts on current codex-cli.

Parallel-teammate machinery deliberately comes last — building the plugin is mostly serial work, and spawn plumbing earns its place only when there are independent stories to parallelize.

**MVP acceptance criterion**: the process catches a real defect in its own construction — the first story-close review finds something the author missed. If it doesn't within the first sprint, the reviewer charters are the bug.

## 11. Open items

1. **Codex R-work inherited from the spike**: the sidecar conflict (implicit skill invocation vs `agents/` sidecar ban) — settle at packaging time; verify hook surface on current codex-cli (spike is one version, explicitly a snapshot; assume churn). Liveness detection is now designed (git pre-commit touchfile check, §3/§7) but needs the same re-verification.
2. **Collision-check value measurement**: instrument the cross-story file check and keep it only if it fires usefully (testimony conflicted; artifacts silent).
3. **Naming** and repo layout for the marketplace (this repo currently `xp-plugin`).
4. **Migration**: none planned — projects adopt fresh; `plan.md`/`constraints.md` can be seeded from an existing SMM by hand once, not by tooling.
