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

#### story-012a — the structured gate; land never spawns   [done]
Context: First half of the story-008-close redesign (work.md 17:43:13Z, 17:56:23Z,
17:57:00Z), split on the seam the 17:33:21Z note named: "a fixing reviewer plus our
current VERDICT-line gate would be strictly WORSE than today". The gate lands first;
012b reverses the reviewer's posture on top of it. Three moves, all deterministic.
(1) LAND NEVER SPAWNS: on drift it refuses, naming `close.py story <id> review`.
Measured over story-008 — land ran 4x, spawned opus 4x, merged 0x, owned the tree
~10 min a run, and a lead edit during one tripped the reviewer-dirtied guard and
blamed the reviewer. (2) THE DELTA PATH IS DELETED: every review covers
merge-base..HEAD. `delta=True` has no CLI surface and cmd_land is its only caller, so
deleting land's call while keeping the path strands dead code behind an unreachable
AC. It also closes the open full_sha bug (17:23:06Z), whose falsifier `grep -q
full_sha` greens on a token — AC 2 is its behavioural red. PRICE, stated because it
is the 17:03:25Z note's option (a) and it is not free: every fix round now costs a
full review of the whole story diff instead of a cheap delta. A fixing reviewer
(012b) is what buys the round count back down. (3) STRUCTURED REPORT replaces the
VERDICT-line grep, which failed twice: forgeable by design (story-002), then defeated
by backticks (story-008). The reviewer writes {fixed[],blocking[],noted[]} JSON — each
item a STRING CARRYING THE FINDING TEXT, so the findings survive outside stdout — to a
round-scoped path under data_root()/reports/, outside the repo and outside markers/,
so it never rides in a fix commit and does not sit in the directory holding its own
gate. Reports are KEPT at close (delete_story_markers clears markers/, not reports/):
they are the audit trail behind a merge body. IT FIXES PARSING, NOT FORGERY: an agent
under bypass writes any path it likes.
WRITE IS DENIED IN THIS STORY. REVIEWER_DENY still blocks Edit/Write/NotebookEdit, so
the reviewer's only route to the report is a Bash heredoc — the charter must name that
route and the exact path, or the first live run ends with ten minutes of opus, prose
findings, no file, and a refusal that looks like a reviewer defect.
DESIGN §6 REPLACEMENT TEXT, so the implementer does not draft process at the keyboard:
land never re-reviews — it refuses and names the review leg; and the two-round cap
survives as a rule THE LEAD applies (constraint 7 reserves exactly that judgment),
restated as "the lead chooses the rounds; land requires the last round to cover HEAD."
DURABILITY (Paul, this session), with its honest bound: the report on disk survives a
reviewer whose stdout is lost, truncated, or unparseable. It does NOT survive a
reviewer killed before it writes — that case wants the tee from the 17:08:23Z note and
is not bought here. Live evidence: this session's plan-reviewer returned nothing twice;
round 2 was told to write a file and the file is what survived.
Size: after the stated moves close.py lands under 500 (constraint 8) — MEASURED at
close: 477, against a plan-review estimate of ~454, with review.py 121 (est. 108) and
bookkeep.py 88 (est. 86). Report parsing, validation, caps and round rendering go to
review.py; merge-body rendering to bookkeep.py beside log_close. Those moves buy the
per-FILE cap, not DESIGN §9's 800-line close COMPONENT budget, which goes 617 -> 686
here (est. 648) and ~730 after 012b — story-009 is what takes it over, and story-010's
ratchet is where that reds.
Files: plugins/xp-plugin/scripts/close.py, plugins/xp-plugin/scripts/review.py,
plugins/xp-plugin/scripts/bookkeep.py, plugins/xp-plugin/scripts/session_start.py,
plugins/xp-plugin/agents/story-reviewer.md, plugins/xp-plugin/agents/plan-reviewer.md,
plugins/xp-plugin/skills/story-close/SKILL.md, plugins/xp-plugin/PROCESS.md,
docs/DESIGN.md, tests/test_close.py, tests/test_session_start.py
AC:
- Given HEAD moved since review, When land runs, Then it refuses naming `close.py story <id> review` and SPAWNS NOTHING (fault-inject: the test reds if land launches the reviewer), and running land twice returns the same answer
- Given a second review round after a commit, Then the bundle carries the WHOLE story diff and not a delta (tests/test_close.py:698 asserts `-A = 1` ABSENT from the delta prompt today; this story inverts that assertion), and land refuses unless the recorded review_base equals today's merge-base AND shown_sha equals HEAD — the full_sha bug, behaviourally: full round, lead commit, land refuses
- Given a clean round, Then shown_sha is HEAD read AFTER the review leg finishes — which under this story's still-present moved-HEAD refusal provably equals the pre-launch HEAD, the pre-launch read staying as that refusal's input. So 012b adds reviewed_head and deletes a guard, and NO assertion written here changes meaning later. This re-expresses tests/test_close.py:644, whose real property is the refusal at :651, not the ordering of a read
- Given trunk moved after a recorded round, When review runs again, Then it REFUSES naming "merge <trunk> into the story branch first" — merge-base does not move when trunk advances, so a re-baseline that leaves review_base unchanged clears land's trunk guard while the reviewer sees nothing new (the full_sha bug's twin on the integration axis)
- Given the reviewer's JSON report, When review runs, Then fixed[]/blocking[]/noted[] land in the close marker with per-item AND per-list caps applied AT THE WRITE; Given a report missing, unparseable, or without those keys, Then the reviewer's raw output is PRINTED FIRST and then review refuses, recording no round — and a bare `VERDICT:` line in prose is NEVER parsed (fault-inject with a prose-only stub reviewer)
- Given a report already sitting at this round's path, When a reviewer writes nothing, Then review refuses and the marker gains no round — the path is unlinked BEFORE the launch, because the round index advances only on a recorded round, so every failed attempt at round N reuses N's path (fault-inject by PLANTING the file, not by observing one)
- Given blocking[] non-empty in the last recorded round, When land runs, Then it refuses naming each blocking item
- Given noted[] items, When land runs, Then it prints them under "file these per PROCESS.md" and the merge body carries them — the filing itself stays judgment (constraint 7)
- Given three review rounds, When land merges, Then the merge body labels them 1/2/3 by list index — a round is recorded only with a valid report, so index IS the round number (round-6 F1: story-008's body read "round 1" for round 6)
- Given a closes.jsonl holding both old verdicts[] records and new ones, When SessionStart renders, Then last_close() renders BOTH shapes and the recovery block stays bounded per-round and in total (round-6 F4, in the section that already evicted constraints.md)
- Given the shipped prose, Then PROCESS.md and SKILL.md contain no "VERDICT" token and carry the §6 replacement text above, and review.charter() names the report path AND the Bash-heredoc route Write denial leaves open — all three assertable, so this is a red test and not a coherence pin
- Given agents/plan-reviewer.md, Then it instructs the reviewer to write its findings to a file before returning (this session's loss, on the leg close.py does not own — prose is the only lever there, so the test asserts the prose)
Verify: pytest -q tests/test_close.py tests/test_session_start.py
Close review: deep
Executor: (default)

#### story-012b — the reviewer fixes; the lead reads its diff   [done]
Context: Second half, safe ONLY on top of 012a's structured gate (work.md 17:33:21Z,
17:33:39Z, 17:43:13Z). Drop REVIEWER_DENY and the reviewer-dirtied-the-tree guard; the
reviewer edits where the code under review is (Path.cwd(), which is the tree the lead
closes from — the lead's checkout for a solo close, a worktree if the lead closes from
one). reviewed_sha becomes three recorded facts: review_base, reviewed_head (what the
reviewer was shown) and shown_sha (post-reviewer HEAD, what the LEAD is shown). Running
land IS assent.
WHAT ACTUALLY RETIRES, precisely: story-008's G1 was never held by the deny-list — a
reviewer with Bash could always `git commit`. It was held by the moved-HEAD /
dirtied-tree REFUSAL, which had TWO jobs, and the card previously named one. Job A:
stop a reviewer certifying its own commit — retired deliberately. Job B: notice that
the LEAD committed while the reviewer held the tree (the measured incident, 17:56:23Z).
Job B is NOT retired; it is re-established by authorship (AC 1), which is strictly
better — it PERMITS the lead's concurrent commit instead of refusing it, and attributes
it correctly instead of blaming the reviewer. That is the tree lock's cheap fix and it
is why the reviewer-in-a-worktree idea is NOT in this card: `git worktree add` refuses a
branch checked out elsewhere, so the reviewer would work detached or on a temp branch,
and the write-back is a merge or rebase against a possibly-moved lead tree — which
re-acquires the lock at write-back and resurrects the merge-conflict path 012a just made
unreachable. Filed as its own card with those two problems stated.
WHAT THE LEAD'S READ CANNOT COVER: the close marker, work.md and closes.jsonl live
OUTSIDE the repo under ~/.xp/data/, so no diff shows them, and the reviewer's Bash can
reach the marker that gates its own merge. That is what AC 6's marker hash is for. (.xp/
IS tracked and IS in the diff — the previous card justified the .xp/ guard with a
sentence describing files it does not protect. The .xp/ guard stands on its own merit:
the reviewer may fix code, never the plan.)
THE THREE-BUCKET CHARTER, which is the cycle-breaker's other half (Paul's call): the
charter today says a gating finding is "one you would not merge over" — indexed to the
reviewer's private taste, and taste cannot be disputed with evidence. It becomes: FIX it
if you can; BLOCK only if you could not fix it AND its failure mode is silent or
corrupting (false green, corrupted record, unreviewed merge — PROCESS.md's existing
finding bar, so this displaces nothing); NOTE the rest. The bar must be COPIED into the
charter, not pointed at: build_bundle never sends PROCESS.md, and DESIGN §8's reviewer
profile deliberately excludes it — so a test asserts the charter's bar sentence and
PROCESS.md's are byte-identical, or this becomes the "rule fixed in one of its two
implementations" defect the story-008 reviewer caught three times.
HONEST SCOPE OF THE WIN: this eliminates the round that exists because the LEAD moved
HEAD applying a prescription — story-008's dominant cost, four of six rounds, and three
of story-012a's. It does NOT eliminate a round when blocking[] is non-empty: reviewer
declines to fix, lead fixes, HEAD moves past shown_sha, land refuses, round 2. And it
MOVES the reviewer-introduced-defect class (story-008 rounds 3, 4, 6; story-012a rounds
2 and 3) from "caught by the next adversarial round" to "caught by the lead's read" — an
author-adjacent reader who has just been told the fixes are trustworthy. AC 8 is the
recovery: the next round is TOLD what the last one changed, which is the detector that
actually found them.
Tests this story deletes, BY NAME (line numbers rot — the previous card's three were all
wrong by the time it was reviewed): test_reviewer_cannot_edit_the_lead_tree_it_is_reviewing
(the deny-list drop), test_a_reviewer_that_commits_is_refused_not_certified (Job A),
test_a_reviewer_that_writes_without_committing_is_also_refused (its target moves to the
UNCOMMITTED write, AC 5). AC 9 must also amend
test_the_charter_names_the_report_path_and_the_route_left_open, which asserts the charter
contains "heredoc" — once Write is allowed that paragraph is stale prose the test would
keep certifying.
Size: close.py is 477/500 and this story is ~+50 without an extraction, which is OVER the
hard cap, not near it (constraint 8). Extraction named UP FRONT rather than discovered at
the keyboard as bookkeep.py was: the reviewer-motion checks — dirty tree, .xp/ touched,
marker unchanged, authorship — are cohesive and belong beside the thing that launched the
reviewer. `review.check_reviewer_motion(reviewed_head) -> str` moves ~35 lines to
review.py and leaves close.py below where it started. The §9 close component goes
686 -> ~735 of 800 either way.
Files: plugins/xp-plugin/scripts/close.py, plugins/xp-plugin/scripts/review.py,
plugins/xp-plugin/scripts/spawn.py, plugins/xp-plugin/agents/story-reviewer.md,
plugins/xp-plugin/skills/story-close/SKILL.md, plugins/xp-plugin/PROCESS.md,
docs/DESIGN.md, tests/test_close.py, tests/test_spawn.py
AC:
- Given a reviewer that edits AND commits in the tree under review, When review returns, Then reviewed_head is the pre-launch HEAD, shown_sha is the post-reviewer HEAD, and no dirtied-tree refusal fires (fault-inject: restoring the old guard reds the test)
- Given ANY commit in reviewed_head..shown_sha not authored by the reviewer identity, When review finishes, Then it REFUSES and names the offending shas — a lead commit made while the reviewer held the tree is otherwise absorbed into shown_sha, land's HEAD==shown_sha holds by construction, and the lead reads his own commit in a range presented as the reviewer's. This is Job B of the guard this story deletes, and it makes AC 3's identity load-bearing rather than decorative (fault-inject: a stub that commits as the lead)
- Given a reviewer commit, Then spawn.py sets GIT_AUTHOR_NAME/EMAIL and GIT_COMMITTER_NAME/EMAIL for role="reviewer" — asserted on the ARTIFACT (`git log --format=%an`), never on the launch env, which passes against a harness that strips it; EMAIL too, or every email-keyed tool still reports the lead
- Given the reviewer committed fixes, When review returns, Then the range, `--stat` and the diff are written to a FILE beside the round's report and BOTH legs print its path — review's stdout is the channel this session lost three times, so the assent artifact must not live only there; land prints the path again before merging
- Given the reviewer returns leaving the tree DIRTY, When review finishes, Then it refuses, describing the uncommitted files WITHOUT asserting who wrote them (that misattribution is the measured complaint at 17:56:23Z)
- Given reviewer commits that touch .xp/, or a close marker whose hash changed across the launch, When review finishes, Then it refuses — the reviewer may fix code, never the plan, and never the file that gates its own merge (fault-inject both: a stub that edits .xp/, a stub that rewrites the marker's blocking[])
- Given a reviewer that hangs, Then run_agent bounds it with a wall clock read from the environment (the suite cannot monkeypatch a subprocess) and surfaces the timeout through the existing rc!=0 path
- Given ANY of the abort paths above, Then ONE message states that the reviewer's commits are in the tree, prints reviewed_head..HEAD --stat, and names `git reset --hard <reviewed_head>` as the undo — "nothing was recorded" was written for a reviewer that could not write, and under this story the tree holds commits from a process that was killed mid-fix
- Given a round after the first, Then the bundle carries earlier rounds' fixed/blocking/noted labelled "do not re-litigate a settled fix; DO verify each fixed item still holds" — a fixing reviewer with no memory re-edits the last round's edits and reverses its deliberate punts, and the next-round-that-knows is the only mechanism that has ever caught a reviewer-introduced defect
- Given the shipped charter, Then it states the three buckets and its finding-bar sentence is BYTE-IDENTICAL to PROCESS.md's; and SKILL.md/PROCESS.md/DESIGN §6 state the split arithmetic — a REVIEWER fix costs no confirming round (shown_sha covers it), a LEAD fix still does — replacing today's undifferentiated sentence in all three
Verify: pytest -q tests/test_close.py tests/test_spawn.py
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
Also deferred here from the story-012 candidate note (17:03:25Z): a CONFIGURABLE
reviewer (`--reviewer` override) — the seam the codex adapter needs. Its two
siblings landed: durable in 012a, bounded in 012b.

#### story-010 — size-ratchet CI   [ready]
Context: DESIGN §9's budgets become enforced acceptance criteria: shipped py
≤5,000 (spawn ≤2,000 · close ≤1,100 · hooks+adapters ≤1,000 · misc ≤900), skill
prose ≤3,000 words, agent prose ≤2,500 words, tests ≤2× code lines. ratchet.py
(stdlib) + a GitHub Action running it on PRs; also wired into pre-push.
The close component is the budget expected to red first: it reaches ~690 of
DESIGN §9's 800 after 012a/012b, and story-009's sprint_close.py takes it over.
Files: plugins/xp-plugin/scripts/ratchet.py, .github/workflows/ratchet.yml, lefthook.yml, tests/test_ratchet.py
AC:
- Given the repo within budgets, When ratchet.py runs, Then exit 0 with a one-line report
- Given comments + docstrings over 20% of shipped Python lines, When ratchet.py runs, Then nonzero naming the density and the worst file — the one budget no test can enforce, because prose is the artifact that goes stale silently (the rubric ships in PROCESS/TEAMMATE/charter; only CI can count)
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

