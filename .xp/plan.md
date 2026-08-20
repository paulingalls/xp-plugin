# Execution Plan — xp-plugin

Source: docs/DESIGN.md (§10 bootstrap order). Sprint 0 (hand-built artifacts) is
this commit. Building proceeds under the process these artifacts define.

## Milestone 1 — A self-hosting core   [in-progress]
Goal: every Sprint-0 hand-rolled piece replaced by the real component, built under
review by the process itself.
Done when: a story on this repo runs plan-review → TDD → story-close (close.py) →
merge with zero hand-steps besides the two judgment points, and the story-close
review has caught ≥1 real defect across the milestone (MVP acceptance, DESIGN §10).

### Sprint 1

#### story-001 — work.md append CLI   [done]
Context: All work records (bug/debt/note) go through one flock'd append CLI so
concurrent writers never lose updates (DESIGN §4). Shapes are structural: bug =
claim + falsifier + files (falsifier must red to file); debt = same, falsifier
green; note = free text. Long free text truncates with a notice, never rejects.
State root: ~/.xp/data/<project-id>/ (project-id from git-common-dir hash).
Files: plugins/xp-plugin/scripts/work.py, tests/test_work.py
AC:
- Given two concurrent appends, When both complete, Then work.md contains both entries intact (flock, no lost update)
- Given a bug entry whose falsifier command exits 0, When filed, Then the CLI refuses with a message naming the green falsifier
- Given a note over the free-text cap, When filed, Then it is truncated with an appended notice, exit 0
- Given no state dir, When first append runs, Then the dir and work.md are created
Verify: pytest -q tests/test_work.py
Executor: (default)

#### story-002 — close.py: story close   [done]
Context: Automates .claude/skills/story-close (the checklist IS the spec). Pipeline:
preflight → spawn story-reviewer (stop: fix-or-ask) → run story Verify + story tier →
verdict into PR body/merge trailer → merge; re-review on conflicted/drifted merge
(DESIGN §6). Sub-budget ≤800 lines.
Files: plugins/xp-plugin/scripts/close.py, tests/test_close.py
AC:
- Given a clean story branch, When close runs end to end, Then exactly one judgment gap exists (reviewer findings, between start and reviewed) — every other step is mechanical with no stop — and the merge commit/PR body carries the reviewer's VERDICT line verbatim
- Given a merge conflict, When resolved, Then close refuses to complete until a re-review covers the post-resolution diff
- Given a red story Verify, When close runs, Then it aborts before merge naming the failing command
Verify: pytest -q tests/test_close.py
Executor: (default)

#### story-005 — sprint-integration branching in close.py   [done]
Context: release: sprint (config.yml) — stories integrate on a sprint branch;
sprint close PRs main (the release moment, where the heavy gates already live).
close.py resolves its target: release==sprint AND config sprint_branch names an
existing local branch -> merge the story into it (config-only per plan review,
constraint 10; a configured-but-missing branch REFUSES, never falls back); else
default branch (today's behavior; story-005 itself closes that way — bootstrap). Trunk
guards target whichever branch integration points at. Schedule BEFORE 003/004:
they land on the sprint branch this story enables.
Files: plugins/xp-plugin/scripts/close.py, tests/test_close.py
AC:
- Given release: sprint and sprint branch sprint-001 exists, When a story closes in local mode, Then it merges into sprint-001 (not main) with the verdict, and the trunk guards compare against sprint-001
- Given release: sprint but no sprint branch, When a story closes, Then it targets the default branch (bootstrap/fallback)
- Given release: story, When a story closes, Then behavior is unchanged
Verify: pytest -q tests/test_close.py
Executor: (default)

#### story-003 — SessionStart hook + recovery block (claude adapter)   [done]
Context: Deterministic injection: VALUES + PROCESS + constraints + session.md
(stamped; STALE prefix when HEAD moved) + recovery block (branch, dirty files, story
states from plan.md, last test status, open work.md items) + liveness touchfile +
enforcement banner (DESIGN §5b, §7). Replaces the CLAUDE.md shim lines.
Files: plugins/xp-plugin/hooks/hooks.json, plugins/xp-plugin/scripts/session_start.py, tests/test_session_start.py, plugins/xp-plugin/scripts/close.py (digest-format prompt only)
Notes: "last test status" in the recovery block defers to story-004's marker. The
CLAUDE.md shim retires at the plugin-load step (post-sprint), where the hook's real
firing is verified via claude --debug — not in this story (plugin not yet loaded
into dogfood sessions).
AC:
- Given a session.md older than HEAD, When session starts, Then the injection prefixes STALE with the commit distance
- Given no session.md, When session starts, Then the recovery block alone is injected (no error)
- Given the hook ran, Then a session-scoped liveness touchfile exists for the git-hook check
Verify: pytest -q tests/test_session_start.py
Executor: (default)

#### story-004 — Stop advisory gate   [done]
Context: Advisory block when the current story's Verify command last ran red —
config-known string match, not heuristic detection; honors stop_hook_active, no
block-count assumptions. Same binding: stale-digest nudge (timestamp compare only).
Requires a session-scoped test-status scratch marker written by a minimal
PostToolUse bash leg (the one sanctioned telemetry exception, DESIGN §4).
Files: plugins/xp-plugin/scripts/stop_gate.py, plugins/xp-plugin/scripts/bash_status.py, tests/test_stop_gate.py, plugins/xp-plugin/hooks/hooks.json (shared with story-003: it owns SessionStart, this story adds PostToolUse+Stop; starts after 003 merges)
AC:
- Given the story Verify last exited nonzero, When Stop fires, Then the gate blocks once with the failing command named, and passes on stop_hook_active
- Given a non-Verify command failed but Verify is green, When Stop fires, Then no block (advisory scope is Verify only)
- Given an in-progress story with commits newer than session.md, When Stop fires, Then the nudge (not a block) asks for the one-line digest update
Verify: pytest -q tests/test_stop_gate.py
Executor: (default)

### Sprint 2 — the process runs itself
Deferred from DESIGN §10's sketch, explicitly: the exit-status-masking bash gate
(§7 item 5) moves to Sprint 3 with the harness adapters — Verify entailment in
bash_status already covers its worst case at the gate that matters.

#### story-006 — /xp-setup scaffold   [done]
Context: The plugin is installable but useless in an unprepared repo. One skill +
script: create .xp/ from templates (constraints seeded from xp-agents' seeds +
the comment rubric — work.md note; config.yml with tiers/caps; system.md and
plan.md skeletons) and scaffold the git-hook wall (lefthook.yml if lefthook is
present, .githooks + core.hooksPath fallback). Never overwrites.
Files: plugins/xp-plugin/skills/xp-setup/SKILL.md, plugins/xp-plugin/scripts/setup.py, plugins/xp-plugin/templates/, tests/test_setup.py
AC:
- Given a bare git repo, When setup runs, Then .xp/ holds seeded constraints.md, config.yml, system.md + plan.md skeletons
- Given lefthook on PATH, When setup runs, Then lefthook.yml is written and installed; Given none, Then .githooks + core.hooksPath carry secrets scan + fast tier
- Given an existing .xp/, When setup runs, Then it refuses without touching anything
Verify: pytest -q tests/test_setup.py
Close review: standard
Executor: (default)

#### story-007 — spawn CLI (claude harness)   [done]
Context: The piece neither harness provides: spawn <story-id> creates a worktree
(or in-place branch) off the integration target, on a named story branch, and
launches headless claude -p with the teammate profile INLINED (VALUES +
TEAMMATE.md — written in this story, DESIGN §8 one-pager — + story card +
constraints; paths are fallback, never the mechanism). harness/model/effort from
the card's Executor: line, else config roles. Codex leg is Sprint 3.
Files: plugins/xp-plugin/scripts/spawn.py, plugins/xp-plugin/TEAMMATE.md,
plugins/xp-plugin/scripts/work.py, plugins/xp-plugin/scripts/session_start.py,
plugins/xp-plugin/templates/system.md, tests/test_spawn.py, tests/test_work.py,
tests/test_session_start.py
AC:
- Given a ready story card, When spawn --dry-run runs, Then the printed command carries the resolved model/effort and the prompt inlines VALUES, TEAMMATE, the card, and constraints
- Given spawn for a story, Then a worktree exists on its branch off the integration target (bootstrap per system.md)
- Given the card has an Executor: override, Then it beats the config default
- Given the worktree already exists, Then spawn refuses
- Given the dry-run prompt, Then its size respects the <2k-token teammate budget (structural assert — DESIGN §8)
- Given two clones with different git identities, When each spawns the same story, Then the branch names are namespaced (<user-ns>/<story-id>-<slug>) and do not collide
- Given a spawn completes, Then the worktree's plan.md reads [in-progress] and the flip is committed on the story branch
- Given the lead executes a story solo, When spawn --in-place runs, Then the story branch is created off the integration target with the status flipped and NOTHING launched — the solo path had no branch step, so solo work landed on the sprint branch
- Given the launched session, Then its argv carries --plugin-dir (the worktree has no marketplace enablement) and the teammate's SessionStart injects the teammate profile, not the lead's
Verify: pytest -q tests/test_spawn.py tests/test_work.py tests/test_session_start.py
Close review: deep
Executor: (default)

#### story-008 — close.py spawns the reviewer (completes Milestone 1)   [done]
Context: Depends on story-007. The verdict becomes PIPELINE-RECEIVED: reviewed
splits into `review` (spawns the story-reviewer headless via spawn.py's runner,
captures its VERDICT line into the close marker — no --verdict flag survives)
and `land` (requires the recorded verdict; merges; greens the story's verify
test-status marker). Drift re-runs review on the delta in-pipeline. Kills the
forgeable-verdict gap and the message-crossing race, both hit in Sprint 1
(work.md notes carry the drift/marker design inputs).
Files: plugins/xp-plugin/scripts/close.py, plugins/xp-plugin/scripts/review.py, plugins/xp-plugin/scripts/spawn.py,
plugins/xp-plugin/scripts/bash_status.py, plugins/xp-plugin/scripts/stop_gate.py,
plugins/xp-plugin/scripts/session_start.py, plugins/xp-plugin/skills/story-close/SKILL.md,
tests/test_close.py, tests/test_stop_gate.py, tests/test_session_start.py
AC:
- Given a story branch, When review runs, Then the reviewer is spawned by the pipeline and its VERDICT line lands in the close marker; --verdict is refused as unknown
- Given HEAD moved after review, When land runs, Then it refuses and review covers the delta in-pipeline
- Given land completes, Then the merge body carries EVERY review round's verdict verbatim, labelled, and NO RED test-status marker for the story survives — close.py DELETES the story's markers; it never writes a green into another session's file (DESIGN §4: gate state is session-scoped, never a record — forging a measurement is the 'gate advances its own state' defect)
- Given reviewer output without a VERDICT line, When land runs, Then it refuses — no verdict, no merge
- Given two in-progress stories with byte-identical Verify commands, When each records a test status, Then they get DISTINCT markers (story-scoped key, not verify-string) — the carried sprint-001 triage input
- Given XP_ROLE=teammate, When close runs, Then it REFUSES — a teammate loaded via --plugin-dir can reach /story-close and close.py through Bash, so a self-close is an unreviewed merge; declaration in TEAMMATE.md is not enforcement (fault-inject it)
- Given land completes, Then the integration branch is PUSHED and the story branch deleted local-then-origin (that order: `git branch -d` checks against the upstream ref, so deleting origin first forces a -D that discards the merged check). Both were hand-steps at story-007 close; M1 allows none.
- Given land completes, Then close.py APPENDS a deterministic close record (story id + title, capped verdict, post-amend merge sha, ISO stamp) to a closes.jsonl log — appended, never overwritten, so it is a log and not the project-global mutable marker constraint 10 forbids — and SessionStart renders the last one in the RECOVERY block — the layer that cannot go stale. recovery_block() filters [done] out today, so what was just completed survives only in the hand-written digest, which is the stale-able layer and a hand-step M1 forbids. close.py writes FACTS only; the narrative digest stays LLM-written (constraint 7 — deterministic Python may not summarize).
Verify: pytest -q tests/test_close.py tests/test_stop_gate.py tests/test_session_start.py
Close review: deep
Executor: (default)

#### story-012a — the structured gate; land never spawns   [ready]
Context: First half of the story-008-close redesign (work.md 17:43:13Z, 17:56:23Z,
17:57:00Z). SPLIT per plan review, on the seam the 17:33:21Z note already named: "a
fixing reviewer plus our current VERDICT-line gate would be strictly WORSE than
today". So the gate lands first and 012b reverses the reviewer's posture on top of
it. Three moves, all deterministic. (1) LAND NEVER SPAWNS: on drift it refuses,
naming `close.py story <id> review`. Measured over story-008 — land ran 4x, spawned
opus 4x, merged 0x, owning the tree ~10 min a run, and a lead edit during one tripped
the reviewer-dirtied guard and blamed the reviewer. (2) THE DELTA PATH IS DELETED:
every review covers merge-base..HEAD. `delta=True` has no CLI surface and cmd_land is
its only caller, so deleting land's call while keeping the path strands dead code
behind an AC no test can reach. The deletion also closes the open full_sha bug
(17:23:06Z) — whose falsifier `grep -q full_sha` greens on a token, the third
falsifier-coupled-to-an-identifier this session; AC 2 is its behavioural red.
(3) STRUCTURED REPORT replaces the VERDICT-line grep, which failed twice: forgeable
by design (story-002), then defeated by backticks (story-008). The reviewer writes
{fixed[],blocking[],noted[]} JSON to a ROUND-SCOPED path the bundle names, under
data_root()/reports/ — outside the repo and outside markers/, so it never rides in a
fix commit and does not sit in the directory holding its own gate. IT FIXES PARSING,
NOT FORGERY: an agent under bypass can write any path it likes, and it is 012b that
knowingly retires story-008's G1 property. Stated here rather than implied away.
DURABILITY (Paul, this session): a reviewer whose stdout is lost, truncated or
unparseable still leaves its findings on disk. Live evidence — this session's
plan-reviewer returned nothing twice and its report survived only by being re-sent by
hand. The plan-reviewer charter gets the same instruction; that leg is carried by the
harness, not by close.py, so prose is the only lever there.
Size: close.py is 449/500 and this story is net-additive (constraint 8). Report
parsing, validation, caps and round rendering live in review.py; merge-body rendering
moves to bookkeep.py beside log_close; close.py keeps gates only.
Files: plugins/xp-plugin/scripts/close.py, plugins/xp-plugin/scripts/review.py,
plugins/xp-plugin/scripts/bookkeep.py, plugins/xp-plugin/scripts/session_start.py,
plugins/xp-plugin/agents/story-reviewer.md, plugins/xp-plugin/agents/plan-reviewer.md,
plugins/xp-plugin/skills/story-close/SKILL.md, plugins/xp-plugin/PROCESS.md,
docs/DESIGN.md, tests/test_close.py, tests/test_session_start.py
AC:
- Given HEAD moved since review, When land runs, Then it refuses naming `close.py story <id> review` and SPAWNS NOTHING (fault-inject: the test reds if land launches the reviewer), and running land twice returns the same answer
- Given any review round, Then it covers merge-base(trunk,HEAD)..HEAD — no delta spelling exists on the CLI or in the code — and land refuses unless the recorded review_base equals today's merge-base AND shown_sha equals HEAD (the full_sha bug, behaviourally: full round, lead commit, land refuses)
- Given the reviewer's JSON report, When review runs, Then fixed[]/blocking[]/noted[] land in the close marker with per-item AND per-list caps applied AT THE WRITE; Given a report missing, unparseable, or without those keys, Then review refuses and records no round — and a bare `VERDICT:` line in prose is NEVER parsed (fault-inject with a prose-only stub reviewer)
- Given a round-scoped report path, When a reviewer crashes or writes nothing, Then review refuses rather than reading the previous round's file — a stale report certifying a round nothing produced is story-008's gate-advances-its-own-state defect (constraint 10: the round is the scope)
- Given blocking[] non-empty in the last recorded round, When land runs, Then it refuses naming each blocking item — the last round governs, and only when its shown_sha == HEAD
- Given noted[] items, When land runs, Then it prints them under "file these per PROCESS.md" and the merge body carries them — the filing itself stays judgment (constraint 7)
- Given three review rounds, When land merges, Then the merge body labels them 1/2/3 by list index — a round is recorded only with a valid report, so index IS the round number (round-6 F1: story-008's body read "round 1" for round 6)
- Given a closes.jsonl holding both old verdicts[] records and new ones, When SessionStart renders, Then last_close() renders BOTH shapes and the recovery block stays bounded per-round and in total (round-6 F4, in the section that already evicted constraints.md)
- Given the shipped prose — PROCESS.md, DESIGN §6, SKILL.md and review.charter() — Then it describes THIS mechanism: no VERDICT line, no round cap the pipeline does not count, and the report path named where the reviewer will read it. A COHERENCE PIN, not a behavioural check; added prose displaces equal weight (constraint 1)
- Given the plan-reviewer charter, Then it instructs the reviewer to write its findings to a file before returning — this session's loss, on the leg close.py does not own
Verify: pytest -q tests/test_close.py tests/test_session_start.py
Close review: deep
Executor: (default)

#### story-012b — the reviewer fixes; the lead reads its diff   [ready]
Context: Second half, safe ONLY on top of 012a's structured gate (work.md 17:33:21Z,
17:33:39Z, 17:43:13Z). Drop REVIEWER_DENY and the reviewer-dirtied-the-tree guard;
the reviewer edits where the code under review is (Path.cwd() — the live tree for a
solo close, the worktree for a spawned one, no code change for that half). reviewed_sha
becomes three recorded facts: review_base, reviewed_head (what the reviewer was shown)
and shown_sha (post-reviewer HEAD, what the LEAD is shown). Running land IS assent.
THIS RETIRES story-008's gating finding G1 — that the tree a verdict names cannot have
been touched by the thing that issued the verdict — it does not replace it. What
carries the weight instead: the lead's read of the reviewer's diff, the story Verify
and tier that land runs, and the commit wall on the reviewer's own commits. What that
read CANNOT cover, and why the .xp/ guard exists: the reviewer runs under
--dangerously-skip-permissions and `git diff` shows tracked files only — not the
marker that gates its own merge, not work.md, not closes.jsonl.
Files: plugins/xp-plugin/scripts/close.py, plugins/xp-plugin/scripts/review.py,
plugins/xp-plugin/agents/story-reviewer.md, plugins/xp-plugin/skills/story-close/SKILL.md,
plugins/xp-plugin/PROCESS.md, docs/DESIGN.md, tests/test_close.py
AC:
- Given a reviewer that edits AND commits in the tree under review, When review returns, Then reviewed_head is the pre-launch HEAD, shown_sha is the post-reviewer HEAD, and no dirtied-tree refusal fires (fault-inject: restoring the old guard reds the test)
- Given the reviewer committed fixes, When review returns, Then it prints the commit range, `--stat`, and the full diff up to a stated char cap — above the cap, stat + range + the command to re-read. The assent premise is "nothing merges unlooked-at", so the mechanism is NAMED, BOUNDED and asserted on stdout; story-008 shipped a defect from an AC whose verb had no artifact behind it
- Given land merges, Then the merge body carries the reviewer's commit range — reviewer commits carry the LEAD's git identity (run_agent sets only XP_ROLE), so nothing in git distinguishes them and DESIGN §6's audit trail is otherwise lost
- Given the reviewer returns leaving the tree DIRTY, When review finishes, Then it refuses naming the uncommitted files — shown_sha must name a commit, and review never commits on the reviewer's behalf
- Given reviewer commits that touch .xp/, When review finishes, Then it refuses — the reviewer may fix code, never the plan, the constraints, or its own gate state (fault-inject)
- Given the shipped charter, SKILL.md and the PROCESS.md stopping rule, Then they describe a fixing reviewer with the lead's read as the judgment point — today's text ("Do not edit code"; "fixes applied exactly as prescribed... close WITHOUT re-review"; "hard cap two rounds") is written for a reporting reviewer, ships to consuming projects, and is injected into every lead session (constraint 1: displace what you add)
Verify: pytest -q tests/test_close.py
Close review: deep
Executor: (default)

#### story-009 — sprint-close pipeline   [ready]
Context: Automates Sprint 1's hand-run close. Lives in its OWN module,
scripts/sprint_close.py, behind a ~2-line `close.py sprint` dispatch (plan
review: dissolves the close.py collision with 008/011 and the 500-line file
cap in one move — the §9 close sub-budget spans the component). May run
parallel to the 007→008→011 chain. `sprint start`: full tier + archive.md
falsifier batch (a red re-files as bug and aborts) + work.md note consumption
(each note: promote to constraints/system via the retro diff, or archive) +
emits the retro skeleton and triage list FOR THE HUMAN. `sprint land`: after
human triage/retro, opens the release PR with version bump + tag; the
sprint_branch key is retired only ON MERGE, never at PR-open (a stalled PR
with a dead key is the v0.2.0 defect mirrored — plan review). Not-releasable →
branch carries, key stays. Boundary: the broad review and LLM security review
stay LLM-present steps named in the sprint-close skill checklist — a hook/
script cannot absorb them (constraint 7).
Files: plugins/xp-plugin/scripts/sprint_close.py, plugins/xp-plugin/scripts/close.py (dispatch only), tests/test_sprint_close.py
AC:
- Given all sprint stories done, When sprint start runs, Then full tier + archived falsifiers execute (a red aborts, re-filed as bug) and every work.md note is emitted for promote-or-archive triage alongside the retro skeleton
- Given human inputs, When sprint land runs, Then the release PR opens with the bump+tag and the digest is written — and the sprint_branch key survives until the PR is MERGED
- Given a merged release PR, When the post-merge step runs, Then the key is retired
- Given a not-releasable call, Then no PR opens and the key survives
- Given a constraint is promoted, Then the append path enforces a per-item AND total char cap and REFUSES over it — constraints_cap counts line-items, not size (10 items = 2,090 chars here), and the predecessor's json bounded size by validating at write, not by being json
- Given any size refusal, Then the message names the cap, the current value, and the next ACTION (which item to retire), and the line that blew is the line that reds — story-007's budget test sent the reader to trim TEAMMATE.md for a defect that was a new agent
Verify: pytest -q tests/test_sprint_close.py
Close review: deep
Executor: (default)

### Sprint 3
DEFERRED HERE AT story-012's plan review (Paul's call): story-010 is where DESIGN §10
already puts it — its presence in Sprint 2 was drift — and story-011 rebases onto
whatever 012b lands, so closing it first would build free mode on a dead design.
Sprint 2 is at its cap of 6 with 012a/012b; these two are what the split displaced.

#### story-010 — size-ratchet CI   [ready]
Context: DESIGN §9's budgets become enforced acceptance criteria: shipped py
≤5,000 (spawn ≤2,000 · close ≤800 · hooks+adapters ≤1,000 · misc ≤1,200), skill
prose ≤3,000 words, agent prose ≤2,500 words, tests ≤2× code lines. ratchet.py
(stdlib) + a GitHub Action running it on PRs; also wired into pre-push.
Files: plugins/xp-plugin/scripts/ratchet.py, .github/workflows/ratchet.yml, lefthook.yml, tests/test_ratchet.py
AC:
- Given the repo within budgets, When ratchet.py runs, Then exit 0 with a one-line report
- Given a fixture tree constructed OVER a budget, When ratchet.py runs, Then nonzero naming the budget and overage (the guard fault-injected, constraint 2)
- Given the workflow file, Then it triggers on pull_request and invokes ratchet.py (structural pin; first live run verified manually at the sprint-002 release PR)
- Given lefthook.yml, Then pre-push runs ratchet.py (structural pin)
Verify: pytest -q tests/test_ratchet.py
Close review: standard
Executor: (default)

#### story-011 — free mode (card-less close)   [ready]
Context: Depends on story-008. Between-sprint tweaks: `close.py free start <slug>`
cuts <user>/free-YYYY-MM-DD-<slug> off the default branch and emits a diff-only
bundle; review via the 008 pipeline leg; `free land` opens the PR to main
including the patch version bump — a free close targeting main IS a release
(v0.2.1 rule, DESIGN §6).
Files: plugins/xp-plugin/scripts/close.py, tests/test_close.py
AC:
- Given free start on the default branch, Then the dated free branch exists and the bundle is emitted without a story card
- Given free land with a pipeline-received verdict, Then the PR to main carries the patch bump
- Given free land without a verdict, Then it refuses
Verify: pytest -q tests/test_close.py
Close review: standard
Executor: (default)

