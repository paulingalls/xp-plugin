# Design — xp-plugin (working name)

*Successor to xp-agents: same spirit, 80–90% less prose and code, dual-harness (Claude Code + Codex).*
*Decisions in this doc were worked through with Paul on 2026-08-19 against the evidence in [AUDIT.md](AUDIT.md). The Codex facts come from xp-agents' measured spike (`CODEX_SPIKE_FINDINGS.md`, codex-cli 0.146.0); the rows story-021's spawn leg rests on carry a re-verified-on-0.147.0 mark or a corrected value in §3.*

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
│   └── constraints.md             the one load-bearing pillar; changes via reviewed diff
└── (git hooks scaffolded via lefthook or .githooks)

~/.xp/data/<project-id>/           (out-of-repo: runtime, shared across worktrees & harnesses)
├── plan.md                        execution plan: milestones + current sprint stories — PER CLONE
├── session.md                     lead's continuity digest (sole writer: the lead's close flow)
├── work.md                        open bugs/debts/notes — all writes via the flock'd append CLI, never direct edits
├── env.json                       machine facts for processes the plugin never spawned: the installed
│                                  plugin root + the version that recorded it (setup seeds, SessionStart refreshes)
├── markers/                       ALWAYS scoped: <story-id>.ready.json (the reviewed card's digest),
│                                  <story-id>.close.json, <session>.test-status — a project-global
│                                  marker is a design error
└── locks/
```

**env.json, and why the read refuses.** A codex-native lead's scripts, and any hook
outside a spawn, have no `${CLAUDE_PLUGIN_ROOT}` and no `Path(__file__)` inside the
plugin — but they can derive the data root from git alone, so that is where the
installed plugin root goes. Project-scoped, never global: two projects may pin two
plugin versions. `setup.py` seeds it; `session_start.py` refreshes it every session, on
both harnesses and both roles. The refresh is load-bearing rather than belt-and-braces:
the codex cache is version-keyed (`~/.codex/plugins/cache/xp-plugin/xp-plugin/<version>`),
so every release moves the path and staleness is the EXPECTED state. The reader
(`env.plugin_root()`, `work.py env`) therefore refuses loudly instead of guessing —
naming the file, the recorded value and the refresh route — and checks the manifest and
the recorded version, because `is_dir()` alone passes on a cache that KEEPS old version
directories. One case is out of its reach and is bounded by the refresh instead: a kept
old directory whose manifest still matches the recorded version is self-consistent. The
version line is also the skew signal — two harnesses can hold two installs, and the last
SessionStart wins the pointer. **`spawn.py` is deliberately NOT a consumer**: spawn runs
FROM the plugin and knows `Path(__file__)`, so reading the pointer for tidiness would put
a refusable lookup in front of the one path that never needs one.

Two harness adapters over one shared core:

- **Shared**: skills (markdown), agent definitions, VALUES.md, planning artifacts, the spawn CLI, a handful of Python helpers (target: ~10 scripts).
- **Git hooks** (scaffolded per project, humans and both harnesses hit the same wall): pre-commit = secrets scan + lint staged + fast tests; pre-push = story-tier tests.
- **CLI hooks**: ONE `hooks/hooks.json`, both harnesses — Claude discovers it from the plugin manifest, Codex by its own default path, and each ignores the other's event names without dropping the rest of the file (§3 table). See §7.

Dual-harness ground rules from the measured spike:

| Codex fact (0.146.0 spike; rows story-021 relies on re-verified on **0.147.0**) | Design consequence |
|---|---|
| Bundled hooks run; `${CLAUDE_PLUGIN_ROOT}` expands; unknown event names silently ignored | **ONE `hooks/hooks.json` serves BOTH harnesses** — Codex loads it by its own default discovery, so NO `hooks` field rides any manifest and no `hooks.codex.json` exists (asserted structurally). **Re-measured 0.147.0, story-025**, because a split file was the live candidate and only a measured divergence may create one: hook `timeout` is **SECONDS** (`timeout: 30` over a 4s hook completed and held the session; `timeout: 3` killed it at 3s — the spike's SessionEnd "3s clamp" is codex's own `clamping SessionEnd hook timeout to {}s`, a seconds value, not a unit mismatch); an unknown event key (`PostToolUseFailure`) and an unknown top-level key (`description`) each leave the rest of the file running; the hook process's cwd is the session cwd; `${CLAUDE_PLUGIN_ROOT}` and `XP_ROLE` both arrive. **So there is nothing to split, and tidiness may not create a second file that can drift** |
| `unified_exec`'s `write_stdin` bypasses `PreToolUse` entirely | **`--disable unified_exec` on every Codex spawn** — non-negotiable spawn flag. **0.147.0: flag PRESENT** (`codex exec --help`), and `spawn.codex_argv` emits it on both legs with a stub that refuses an argv without it. **Re-verified 0.147.0**: `unified_exec` is a KNOWN feature key — `--disable <unknown>` exits 1 with "Unknown feature flag", so a renamed key kills the spawn instead of quietly leaving the gate open (measured at story-021 close via `codex debug prompt-input --disable …`, which parses config without a model call; **re-verified 0.149.0** — unknown feature keys still exit loud). **Still unmeasured: that disabling the key removes the bypass** rather than the flag being accepted and inert — that needs a spawn, so it rides the lead's live walk |
| Headless `codex exec` can never ask the user anything; Plan mode can't write | Teammate prompts must be fully pre-answered (already our contract); lead-side questions ask in chat and record via a CLI leg that requires the answer text. **Re-verified 0.147.0 and 0.149.0**: `codex exec` takes no `-a`/`--ask-for-approval` (measured: "unexpected argument"), so approval is not a knob we set. It DOES expose two approval-shaped flags, and both are ones we must never pass: `--approve-for-me` routes approvals through an automatic model review (judgment where a gate belongs), and `--dangerously-bypass-approvals-and-sandbox` silently voids our `--sandbox workspace-write` — asserted ABSENT from the argv, since asserting the sandbox flag PRESENT does not bound it |
| ~~A failed tool call fires `PreToolUse` and then nothing~~ — **FALSIFIED on 0.147.0** (story-025 probe): `PostToolUse` fires for failures too, and NO field of the Codex payload carries the outcome — `tool_response` is the merged output STRING (`""` for `false`), where Claude ships a `{stdout,stderr,...}` dict. The binary's own `post-tool-use.command.input` schema sets `additionalProperties: false`, so the absence is exhaustive | **`bash_status` writes green only where the payload PROVES it** (`tool_response` is a dict), never inferred from the event. Under Codex it writes NOTHING: red and green are indistinguishable, so a green would erase a real red and release the Stop gate silently — this repo's worst shipped failure mode, and worse than no gate because the banner says the gate is live. Inferring red from the output string was REFUSED: interpretation in a hook is constraint 7. **Consequence, MEASURED at story-025 close, not inferred**: markers are session-scoped (§4) and `stop_gate` globs its OWN session's key only, so with nothing writing one under Codex a Codex lead's Stop gate is INERT — it never blocks, and a red planted by a Claude session is invisible to it. Not bounded nagging: no nagging. The Verify guarantee on Codex is the one it is on Claude — `close.py` running Verify itself, and the git-hook wall |
| Hooks a user has not reviewed are skipped **silently**; the plugin cache is version-keyed | Headless trust is `--dangerously-bypass-hook-trust`; interactive is a `/hooks` review per content hash, **re-reviewed after every update**. Any install doc must say both, and must make manifest bump → reinstall one atomic sequence — without the bump the previous cached copy runs and a walk reports "the hook did not fire" over stale code. And because a skip is silent, liveness detection lives in the layer that cannot be skipped: the scaffolded **git pre-commit warns "CLI-gate liveness unknown"** unless the SessionStart hook left a current touchfile. The SessionStart banner (version + live gates) is the friendly path, not the guarantee |
| A gated model synthesized a hook payload and forged the release marker | CLI-hook markers are **advisory** on every harness; hard enforcement lives in git hooks; markers are lane-keeping, not security |
| `agent_type` doesn't discriminate on Codex; skills aren't tool calls | No gate may key on agent identity or `PostToolUse:Skill`; gates key on cwd + explicit marker files |
| `--disable unified_exec` protects spawns only — a user-launched interactive Codex *lead* is not a spawn | Install/preflight writes the disablement into **user-scope Codex config**, not just spawn flags |
| Codex delivers a skill *locator*, not the body; `!` preloads never expand | Skill bodies must be self-contained prose the model reads itself — no preload commands, nothing load-bearing outside the file |
| No `--plugin-dir` equivalent for `codex exec` — **re-verified 0.147.0** (nothing in `exec --help` loads a plugin ad hoc) | A Codex teammate or reviewer needs **no install**, because `spawn` INLINES the whole profile (VALUES + TEAMMATE + card + constraints) and the wall is lefthook, which is harness-independent. User-scope install is required only for what the profile cannot carry — skills, hooks, the SessionStart banner — which is story-025's surface, not a preflight that exists today |
| Codex filters what its shell inherits, through THREE `~/.codex/config.toml` keys, all measured present on 0.147.0 and re-verified 0.149.0 from codex's own error text for a bad value: `shell_environment_policy.inherit` (`core \| all \| none`), `.exclude` (patterns dropped) and `.include_only` (patterns kept) | Our two hardest gates are ENVIRONMENT variables — `XP_ROLE` (close.py refuses a non-lead, and an ABSENT value reads as `lead`, so it fails OPEN and SILENT) and `GIT_AUTHOR_*`/`GIT_COMMITTER_*` (what `check_reviewer_motion` reads; its absence fails loud, as a stray-commit refusal). On Claude they arrive by plain process inheritance; on Codex a config file we do not own decides. So **all three keys are pinned on every Codex argv** (`inherit=all`, `exclude=[]`, `include_only=[]` — `[]` is each list key's own default, so the pin restores rather than invents). NOT `ignore_default_excludes`: its default strips `*KEY*`/`*SECRET*`/`*TOKEN*`, matching no gate of ours, and clearing it would hand a sandboxed agent the lead's secrets. The story-021 walk measured delivery on the LEAD's box, which is exactly the config that was never going to filter |
| `.git` read-only under `workspace-write` in a LINKED worktree — the spike was RIGHT, and the 0.147.0 probe that read it as falsified was CONFOUNDED (its scratch repo sat under `/tmp`, sandbox-writable by default): measured for real at the first live codex fixing review (bug 0c31ac94), which fixed four files and could not commit | **`spawn.common_dir_widening` adds `--add-dir <git common dir>` at launch for linked worktrees only** — a main checkout's `.git` is already inside the workspace and stays unwidened. The argv carries exactly one `--add-dir`, for the data root (round reports, teammate logs), which is asserted. The commit contract is held EMPIRICALLY instead: the story-021 walk must land a commit, and `spawn.unclean_teammate_result` refuses a teammate that made none — a codex regressing to 0.146.0's behaviour reds at the wall, not in a stub |

### 3b. The plan is PER CLONE, and what that costs

`data_root()` hashes the git-common-dir, so three clones of one repo already have
three state roots and every worktree of one clone shares its clone's — the sharing a
spawned teammate needs, with no new mechanism. `constraints.md`, `config.yml` and
`system.md` stay in the repo: three streams on one codebase obey the same rules, a
constraint promoted in one binds the others, and `system.md` describes the SYSTEM,
not the work.

Stated as decisions, not discovered later:

1. **The plan stops being git-versioned.** Measured on this repo: the CHANGELOG
   carries release narrative and `docs/retros/` the sprint narrative, but card-level
   deliberation — why 013 and 015 were cut, why 014 moved behind 010, three estimate
   revisions — lives ONLY in commit messages on plan.md. After the move, PROCESS's
   existing rule is the sole record: decisions go in work.md with the value tradeoff
   named. That discipline stops being belt-and-braces.
2. **A fresh clone starts with no plan.** Correct for this model — a new clone is a
   new stream — but `xp-setup` scaffolds into the state root, and nothing carries a
   plan between machines.
3. **Sprint membership and the release become per-stream.** `sprint_stories()` reads
   one clone's plan, so a release describes THAT stream's sprint. Coherent here; it
   would not be under a single shared sprint.
4. **The card becomes LIVE.** `close` reads the card from a shared mutable file
   instead of from the story branch, which pinned it at spawn. The good half is why
   plan.md stopped serialising lanes: no card edit invalidates an in-flight review.
   The bad half was that a lead editing a card mid-story silently changed what land
   runs and what the reviewer was shown, with no diff to record it. CLOSED at the
   sprint-4 review, by the credential story-023 shipped after this cost was written:
   `land` re-checks the ready digest and refuses, naming the drift, because the
   card's `Verify:` line is a gate it SHELL-EXECUTES. What is left is the window
   between spawn and that review, where the edited card at least reaches a fresh
   reviewer in its bundle.
5. **Two residual write hazards, both practice rather than property.** `edit_plan`
   serialises the tools' own writers under a flock, but the lead's Edit tool takes no
   lock — lead-vs-lane is last-writer-wins, so don't hand-edit the plan while a lane
   is landing. And the reviewer-motion guard digests only the story's OWN card: a
   whole-plan digest would be the project-global mutable gate §3 forbids, letting a
   sibling lane's flip refuse an unrelated review. A fixing reviewer rewriting
   ANOTHER lane's card is therefore uncaught by mechanism, and rests on the
   story-reviewer charter plus that lane's own next review digest.

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

**Plan** (multi-file work): draft plan → **fresh-context plan reviewer** (independent subagent; checks TDD ordering — red before green, real-behavior-not-reachability — artifact coherence: plan vs stories vs Verify commands vs collision declarations, constraint conflicts, sprint cap; writes findings to `<data-root>/plans/<story-id>.md`, and to `<story-id>.round-N.md` when an earlier round is already there — one name written once per round destroys the round before it) → address findings → `spawn.py ready <story-id>` mints a digest of the whole card block and flips [planned] → [ready] → execute; spawn recomputes that digest and refuses, naming the drift, when the card was edited after its review (the bracket alone was a credential with a reader and no writer — measured three times in sprint-003). The reviewer prompt is a page, not 3,153 words.

**Story** (solo or teammate): red → green → refactor, commit small via git hooks. At story close, **close.py spawns the story reviewer itself** — exactly **one reviewer**, whose charter carries both the process lenses (fault-injection on every new guard *and* filed falsifier, artifact coherence, scope honesty, constraint drift) and the correctness angles (state/lifecycle, removed behavior, cross-file + the copy, line-scan, ecosystem pitfalls, environment assumptions). Its **depth (`standard | deep`) is assigned by the plan reviewer** at plan time — never by the author, who reliably underrates the risk of their own design — and the lead may raise it, not lower it. The lead verifies findings directly (no separate adversarial-verify stage). It then stops for the fix-or-ask judgment, runs `Verify:` + story-tier tests, and merges. **Review stopping rule**: one full review always; the REVIEWER fixes what it finds in the tree under review and the lead reads its diff, so a reviewer fix is owed no further round of findings and no confirming round — it is inside the round that found it; a LEAD fix moves HEAD past what the review covered and still costs one confirming round; a further round of findings is owed only for deviations, uncovered new behavior, or conflict resolutions; what ends the rounds is the finding bar (silent or corrupting earns another; loud does not), never a count — a two-round cap was tried in sprint-002 and retired: nothing counted it, its arithmetic was rewritten twice in a day, and when the human invoked it the mechanism had no way to honour him. Review loops have steeply diminishing returns and the loop-breaker is judgment, not iteration. The reviewer writes a **structured report** — `{fixed, blocking, noted}` — to a round-scoped file the bundle names, and every round is written into the **merge-commit body** labelled by its number, git-versioned where the audit trail outlives every runtime file. The report replaces the VERDICT line the pipeline used to grep, which was forgeable by design and then defeated by backticks; it fixes parsing, not forgery. **Review and merge are separate commands.** `review` is LLM-present, slow, and owns the tree while it runs; `land` is deterministic, mutates only refs, and **never spawns** — it refuses while the last round has blocking findings, while the recorded round does not cover the current merge base, or while a gate the round rested on has moved since — a GATE_FILE, or the story's own card, which no diff can show now the plan lives outside the repo — naming the review leg each time. Two things it deliberately does NOT refuse on, because both were measured serialising stories the sprint planned to be file-disjoint (story-018). **Trunk motion: overlap, not motion.** A review covers the STORY's own changes, computed from its fork point; trunk moving costs a round only where the files trunk changed intersect the files the story changed, and then the refusal NAMES them — that message is also the cross-story collision detector §11 item 2 asks for, since the practice it defends (parallel stories have disjoint file domains) is a human one nothing else watches. Motion still costs something, just not a round: land **trial-merges** (`merge --no-commit --no-ff`, run, always abort) and runs `Verify:` + the tier on the merged tree, because the old refusal's real work was forcing `git merge <trunk>` onto the story branch, and without that nothing ever executes the merge result. Something EXECUTED it and someone REVIEWED it are two properties, and only the second needs a reviewer. **Post-review HEAD motion: report, not refuse.** A lead commit after the recorded round is printed as its own labelled range — never folded into the reviewer's — and merges; a HEAD that no longer CONTAINS what was shown still refuses, because there the recorded round describes no tree that exists — and the REVIEW leg refuses the mirror case, a reviewer that rewrote history, which every downstream check would otherwise pass over: `reviewed_head..HEAD` is ancestry-blind, and shown_sha is read too late to notice; the confirming round it owes survives as a norm the lead honours, not a wall land builds. What is NOT covered either way: an interaction neither the suite nor a conflict can see (two stories adding the same CLI subcommand in different files), where the sprint's own review is the only net. Measured at story-008: a land that re-reviewed ran four times, spawned four reviewers, and merged nothing. One review per story — the per-commit cadence option is gone.

**Branching** (from xp-agents' doctrine, taxonomy dropped): `release: sprint` (default) — a sprint branch off main; stories merge there via close.py; **the PR to main lands when the batch is releasable** — usually sprint close (keep sprints small enough that it is), occasionally carried to the plan/milestone boundary when it isn't; prefer flags/config that dark-launch unready behavior over holding the branch (a sprint branch carried past ~2 sprints is drift risk). Either way the release moment coincides with the heavyweight gates. `release: story` for projects where per-story release is right. No stage taxonomy, no migration machinery. **Main only moves by release**: every merge to main bumps and tags. Between-sprint tweaks ride a free branch — a story branch without a card (reviewer on the diff, PR); a free close targeting main is a patch release.

**Acceptance** (from xp-agents' doctrine, condensed): two loops on two clocks — the commit loop proves code correctness, the story loop proves *product* correctness at the system's external boundary. system.md declares the project's surfaces; every story's ACs are executed by a surface-driving test named in its Verify (Gherkin-executed where the project has a runner, story-tagged like legacy's `@story` features); the plan reviewer flags ACs with no executing test and surfaces with no harness; `/xp-setup` scaffolds harnesses per surface. The plugin ships no Gherkin runner (stdlib constraint) — it uses the project's.

**Sprint close**: **archived falsifiers batch-run** (reds re-file as bugs) → full-tier tests (again at `land`, and there on the TRIAL MERGE with the default branch, through the story leg's own gates: what ships is this branch merged, which no leg here builds) — cheap checks before the expensive one, because the batch refusing after a 25s tier is a refusal it could have reached instantly → **retro: a short narrative (Keep/Fix, one page) + a proposed diff** to `constraints.md` / `config.yml` / test commands, reviewed like any other change. A learning that changes nothing executable or injected is not recorded. → then the sprint close runs **ONE review in four stages** (story-022, revising story-014): `close.py sprint <id> review` — no `--lens`, one marker family. **N blind finders**, one per file in `scripts/angles/*.md`, each reading ONLY its own angle and each over the WHOLE diff; then **BATCHED verification**, one agent judging several candidates with the batch count bounded by `review.verify_batches` in config.yml (default 2) and never by the candidate count; then **one fixer**, which applies the survivors in the tree and commits; then **one closing pass** that looks for BLOCKERS ONLY over the tree the fixer left. The recorded round is the fixer's report plus whatever the closer still blocks on — refuted candidates are recorded nowhere, because the filter is the point. Each stage's bundle is built at ITS launch (the closer must diff the tree the fixer left) and carries the diff against the DEFAULT branch, the sprint's cards, the resolutions filed during the sprint with the claim and original falsifier each replaced, PROCESS/VALUES/constraints/system, and the one `## <stage>` section of the sprint-reviewer charter that is its own. **Why three shapes are one shape now**: measured at sprint-003's close over one release diff, a multi-angle pass found four CONFIRMED silent defects a whole-diff reader missed, because nobody holding a whole diff carries one question across every line — and it cost 1.47M tokens against 135K, because 22 refuters (one per LOCATION) killed 3 candidates. Blind angles buy the first; batching pays for it. **Two bars, not one** (Paul, at that close): CONFIDENCE stays generous — PLAUSIBLE is the default and the verifiers decide — while CONSEQUENCE is strict AT FIND TIME, carrying PROCESS.md's finding bar into every finder's prompt; conflating them is why the report was long, and tightening confidence instead is how a review quietly stops surfacing what it exists for. **The angles are prose** (`.md`, project-neutral by construction: whether a security finding exists is the consuming project's answer), so the library grows additively at zero mechanism cost — a fourth angle is a file. It starts at three: state/lifecycle, checks that cannot fail, and what the change made reachable. **Security is an ANGLE, not a lens**: this knowingly retires story-014's two-lens split, three commits after it landed, and with it `check_report_only` — the sprint reviewer MOVES the tree now, so the report-only mechanism is replaced by the story leg's `check_reviewer_motion` (dirty tree, marker digest, authorship, `.xp/` scoping), and `sprint land` gains the matching **authorship-aware range**: a delta since the recorded round is covered when every commit in it is the reviewer's own, which is the afbd01a3 wedge (a review invalidated by the fixes it produced) closed the way the story leg already closes it. Never over a GATE_FILE, whatever signed it. Otherwise land refuses unless the round covers HEAD with empty `blocking[]`, exempting only a delta entirely under `.xp/` (the retro and digest commits land after the review; the exemption rests on the retro diff having its own human review at triage, never on `.xp/` being harmless, and code motion is never exempt). The review therefore runs AFTER note triage and the retro, or completing the close invalidates the review that permits it. A second round carries the earlier round's findings labelled *validate, do not re-derive* — the mode switch that bounds it, which sprint-002's close did not have and paid for with an unbounded re-review. Broad review **via the Workflow tool** is gone: spawned stages, the same shape as the story leg, work on a Codex lead too. Debt triage for the next sprint happens here with the human (schedule-or-drop), under the same finding bar: only silent-or-corrupting failure modes earn work; loud self-healing corner cases are left to fail loud — a never that later matters returns as an evidence-bearing red. This is what stops each sprint's reviews from generating the next sprint (the predecessor's ballooning mechanism).

**The close pipelines are scripts, not prose.** Each close skill is: run `close.py <scope>` (preflight, push, PR, gates, merge, cleanup — deterministic), which **stops at the two judgment points**: presenting reviewer findings (fix vs ask) and the human triage. ~15 sequential prose turns become 1 script + 2 decisions.

## 7. Enforcement floor

Git hooks (scaffolded by the plugin into the project, shared by humans + both harnesses):

1. **pre-commit**: deterministic secrets scan · lint staged files · fast-tier tests
2. **pre-push**: story-tier tests

CLI hooks (one registration file, both harnesses) — **advisory lane-keeping by declaration**: the spike proved a determined agent can forge or evade any CLI-hook gate on either harness, so nothing below is claimed as a hard property. The hard properties live in git hooks and in close.py running things itself:

3. **Stop**: advisory block when the current story's **Verify command** last ran red (a config-known string, not heuristic command detection — heuristics lose to the six-spellings evasion class), honoring `stop_hook_active` with no block-count assumptions; same binding carries the stale-digest nudge (§5b). The real done-guarantee is close.py running Verify itself.
4. **PreToolUse (bash)**: exit-status-masking block on test commands, with both escapes documented **in the block message**: `# exit-status-not-needed` and `# fault-injection` (a red is the expected outcome there — the design's favorite norm must not trip its own gate)
5. **SessionStart**: role-profile injection + recovery block + enforcement banner (version, live gates) + liveness touchfile for the git-hook check

That's the whole floor: 2 git hooks + 3 CLI bindings, replacing 34. There is no review-marker gate: story-review enforcement moved *inside* close.py (§6) and the plan-review credential *inside* spawn (§6), where there is no marker to forge — a PreToolUse write-block on a plan-reviewed marker was designed here and never built, and the digest retires the design rather than owing it. Everything else — red-first ordering, refactor discipline, coherence, scope honesty, fault injection — belongs to the reviewers, where the audit shows it actually gets caught.

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
- `config.yml` sets defaults per role — e.g. `lead: claude/opus`, `executor: claude/sonnet/medium`, `reviewer: codex/<model>/high`, `plan-reviewer: <harness>/<model>` — and the lead overrides per story in plan.md with one line of stated reasoning. The card carries `Executor:` and `Reviewer:` as twins (story-026): a global reviewer choice cannot express "author codex, review claude" on one story and the inverse on the next. No tier tables, no latching, no executor state machine.
- Codex spawns always carry `--disable unified_exec` and the documented sandbox flags; Codex teammates must be pre-answered (no user-interaction surface headless) — which the story shape already guarantees (context + files + ACs + verify).

**A Codex teammate is not at parity with a Claude one (story-021 ships the spawn; story-025 owns the rest).** Stated here so a reader does not infer parity from "both harnesses spawn":

- **No CLI-gate surface at all**: no SessionStart injection, no stop gate, no `bash_status` marker. The teammate's Verify state is therefore invisible to the lead's recovery block, and no liveness touchfile is written — today nothing at the wall reads one, so nothing refuses. **story-025 ships that surface for a HUMAN-RUN Codex lead, not for a spawned teammate**: `codex_argv` carries no `--dangerously-bypass-hook-trust`, so a spawned teammate's hooks are skipped silently even once the plugin is installed — and even with hooks it would get no Verify telemetry (row above). Both remain open.
- ~~**And no subagents, which costs one PROCESS step**~~ — **CLOSED at story-026.** TEAMMATE.md used to tell a teammate to spawn the `plan-reviewer`; with no `--plugin-dir`, `agents/plan-reviewer.md` is not even present in a Codex teammate's tree, so that step had no mechanism and was skipped or invented. The profile now carries the INVOCATION — `scripts/plan_review.py <story-id> <plan-file>` — never the charter body (3693 tokens against a 2500 target): the script reads `agents/plan-reviewer.md` beside itself, so reaching the script implies reaching the charter, and launches the `plan-reviewer` role headlessly through the same runner every other leg uses. No subagent call rides a harness Agent tool any more, which is what makes plan review a ROLE with a harness/model/effort rather than a Claude-only step.
- **The sandbox is asymmetric, and no stub can show it.** A Claude teammate runs unbounded in its throwaway worktree; a Codex one runs under `--sandbox workspace-write` with `--add-dir` for the data root and network off by default — **measured 0.149.0** (Sprint-5 open probe): DNS refused inside the sandbox (curl exit 6), and `-c sandbox_workspace_write.network_access=true` restores it (HTTP + exit 0). Story-026 shipped that flag on the codex EXECUTOR argv only — the leg that must nest a headless plan review — so reviewer legs stay network-off and the widened executor remains strictly narrower than the unsandboxed Claude leg. **Walked at story-026, both directions**: with the flag, a codex `workspace-write` session ran `plan_review.py`, which launched a nested `claude -p` that reached the API, used its own credentials, and wrote findings to the data root through `--add-dir` — so the open probe's sockets result extends to credentials, which it did not prove. Without it the nested harness dies (`is_error`, `duration_api_ms: 0`, zero turns) and the leg refuses with exit 2 rather than reporting an empty review. A story needing an out-of-tree write still succeeds on one leg and fails on the other.
- **Both harnesses stream natively.** Claude's `stream-json` result envelope and Codex's `--json` last completed agent message are reassembled for callers while the raw JSONL is tee'd live. Once the first session event arrives, the log points at the harness-native transcript under `~/.claude/projects/` or `~/.codex/sessions/`; `spawn` still verifies the tree rather than trusting an in-band report.
- **What is NOT degraded**: the wall (lefthook: lint, secrets, tests at commit, full suite at push), the completion contract, the `{fixed,blocking,noted}` report contract and its round path. Those are shared code, and the codex leg reaches them through the same functions.
- **The reviewer default does not flip to Codex this sprint.** The mechanism ships role-agnostic; the story leg contracts a *fixing* reviewer (story-012b), and pointing every close at a harness whose commit support story-021 is still proving would degrade every close. The `config.yml` flip is a later, separate decision. Row 65 above — writing the `unified_exec` disablement into user-scope Codex config so an interactive Codex *lead* is covered too — is likewise still open.

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

The 5k-line total is **sub-budgeted now**, because honest arithmetic says the two surviving big components already threaten it (the predecessor's spawn subsystem alone is ~1.7k+ lines, and the Codex leg's measured requirements — sandbox flags, install preflight, catalog re-enumeration, tier handling — are feature surface, not prose): spawn CLI ≤ 1,435 · close component ≤ 1,740 · hooks + both harness adapters ≤ 1,000 · scaffolding/validators/misc ≤ 825. (Close was 800 and misc 1,200; sprint-002 moved 300 between them, and sprint-003 moved a further 150 at story-010 under constraint 1's displacement rule — reviewed, and mechanically zero-sum since ratchet.py asserts the sub-budgets sum to the total. The sprint-003 move is priced on story-014's plan-reviewed +125-165 and story-011's +60-80 against a component measuring 1,041; misc funds it from 503 of 900. The 800 was set when the reviewer only REPORTED — one that fixes needs motion checks, an authorship gate, an abort/undo path and an audit artifact, and sprint_close.py is still to come. Misc funded it because its measured occupancy is ~640 of 1,200. Sprint-003 moved a further 50 from spawn at the land-off-worktree fix, priced to that fix's measured need and not to a reserve: spawn measured 567 of 2,000 and the change put close at 1,281. Sprint-004 moved 150 more spawn→close at sprint open — Paul's call at the plan review, which found THREE consumers (the sprint-open bug batch, story-018, story-022) each claiming an unnumbered rebalance against a component at exactly 1,300/1,300; one sized move beats three mid-story escalations, and spawn still holds ~1,230 lines of headroom ahead of the codex leg. A second sprint-004 move of 120 followed at story-022, which measured close at 1,523 against real headroom the first move had already spent (story-018's overlap.py landed after 022 was priced): 73 measured + the filed flip fix + margin for review rounds and story-011's possible return — sized by Paul to end the sprint's escalations, with check_report_only's 22-line deletion after 022 merges as the known payback. A third sprint-004 move of 150 came with story-011's mid-sprint reinstatement (Paul: "if it fits, we can add it"): close measured 1,526 of 1,570 against free mode's plan-reviewed +60-80, and spawn measured 689 with the codex leg fully landed — its allocation was priced for an adapter that came in ~900 lines under, so the move returns what the codex estimate over-reserved. A fourth move of 20 closed the sprint: the release review's one blocker (sprint land's missing dirty-tree refusal, bug 151ee405) needed 2-3 lines into a component its own fixer had left at 1,719/1,720 by displacement — Paul sized the slack rather than risk hunting deletions in just-reviewed code. A fifth move of 75 (spawn→misc) came at Sprint-5's 026+027 integration: plan_review.py (~155 lines, misc by path) and env.py (~110) each fit misc's headroom alone and the sprint preamble never priced their SUM — the overrun surfaced at the first tree holding both, which is the wall doing its job; Paul sized margin through 027's remaining round and story-028. NOTE, because the earlier prose here was read as a funding argument it does not support: `ratchet.component_for` has no notion of a harness adapter, so the Codex leg lands in MISC or SPAWN by PATH, whatever this paragraph reserves.) If a sub-budget blows, the **pre-named sacrificial features** are cut first — teammate output filtering, worktree differential reporting, per-tier effort maps — never the gates or the reviewers. Constraint 8's 500-line per-file hard cap is measured by the same command, **tests included** (sprint-004, Paul: tests are production code); the three grandfather pins it opened with are the files' then-current sizes, may only fall, and red as stale once their files split under the cap.

**How it stays small** (the audit's §5 lesson, inverted): every added rule must displace one (the ratchet enforces the totals); incidents become reviewer-checklist lines or constraints.md entries — never new hooks or new prose steps; anything that can't fail — can't tell you something you didn't believe — doesn't ship.

## 10. MVP and bootstrap order

The product is mostly prose and artifacts, so the MVP is **hand-writing the files the plugin will later scaffold** — the dogfood artifacts become the shipped templates. Enforcement in the MVP comes only from the two layers that need no plugin code: git hooks, and CLAUDE.md (natively injected every session — it stands in for the SessionStart hook until the real one exists).

**Sprint 0 — hand-built, no plugin machinery (~half a day):**
1. `.xp/` written by hand for this repo: the plan (the plugin's own first sprint, stories with Verify commands; in the state root since story-019), constraints.md (seeded from the audit: fault-injection norm, every-rule-displaces-one, no bookkeeping mechanisms), system.md, config.yml (pytest fast/full tiers).
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
2. **Collision-check value measurement**: story-018 built it as land's overlap refusal (§6) rather than as a separate check — keep it only if it fires usefully (testimony conflicted; artifacts silent).
3. **Naming** and repo layout for the marketplace (this repo currently `xp-plugin`).
4. **Migration**: none planned — projects adopt fresh; the plan and `constraints.md` can be seeded from an existing SMM by hand once, not by tooling. A project scaffolded before story-019 keeps a stale in-repo `.xp/plan.md`; the missing-plan refusal names the move (there is no migration command — one-time work for a population of one).
