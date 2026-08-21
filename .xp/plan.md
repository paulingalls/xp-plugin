# Execution Plan — xp-plugin

Source: docs/DESIGN.md (§10 bootstrap order). Sprint 0 (hand-built artifacts) is
this commit. Building proceeds under the process these artifacts define.

## Milestone 1 — A self-hosting core   [done]
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
#### story-009 — sprint-close pipeline   [done]
Context: Automates Sprint 1's hand-run close, in its OWN module,
scripts/sprint_close.py, behind a ~2-line `close.py sprint` dispatch. close.py is
474/500 and the §9 close component is 821 of the 1,100 it was raised to, so this
story has ~279 lines of headroom and the ≤20% prose bar applies (shipped-wide is
17.0%; close.py's 11% is the style that fits, bookkeep's 25.6% is not).
`close.py sprint <id> start` — MEMBERSHIP IS AN ARGUMENT, never derived from
sprint_branch (that key may not survive this story): a sprint's stories are the
`####` cards between `### Sprint <id>` and the next `###`. Runs the full tier, the
falsifier batch, note consumption, and EMITS the retro skeleton, the triage list
and the digest PROMPT for the human — it never writes the digest itself
(constraint 7 reserves summarizing for LLM-present moments; close.py's story leg
already ends by telling the lead to write it).
RECORDS NEED AN ID AND A RESOLUTION, and both are measured, not assumed. MEASURED
by plan review: 48 concurrent appends through the CLI produced 48 IDENTICAL `##
kind ISO` headings, and the live work.md already has 6 colliding heading values,
one shared by three entries. So a timestamp is not a name and "resolve the record
at 03:41:29Z" silences three records, two of them live. The id is
sha256(entry text)[:8], minted inside the lock the append already holds — stable
by construction because the file is append-only, and derivable for all 53 legacy
entries, which can never be backfilled.
RESOLUTION IS A SUBSTITUTED FALSIFIER, NOT A DELETION. A resolution that merely
marks a record done is an unchecked assertion: one command silences a live bug
forever, and the batch is the only thing that ever re-reads a filed bug. Instead a
resolution CARRIES a replacement falsifier that must be GREEN NOW (the same
enforcement point work.py already uses for the bug/debt asymmetry), and the batch
RUNS it rather than skipping the record. A resolution that was wrong therefore
REDS LATER and the record reopens. This also lands the diagnosis that motivated
the story: the full_sha bug's falsifier greps an identifier its fix renamed, so
`resolve` refuses it until a behavioural falsifier is supplied — which is exactly
what should happen, and is the third identifier-coupled falsifier this sprint.
CORPUS IS BOTH (Paul's call, and a DESIGN §4 amendment this story writes):
unresolved bug/debt falsifiers in work.md AND archive.md's dropped-debt ones. §4
said work.md records have no lifecycle; that is what the resolution verb changes.
POLARITY, and it is a live landmine: a debt/archived falsifier asserts THE SYSTEM
IS STILL OK — red means the latent problem materialised. The 04:56:26Z debt is
INVERTED (green because the flaw is present, red once the sprint_branch key is
removed), so the first live batch would abort this very sprint close and re-file
the fix as a bug. It needs a human disposition before the batch first runs, and
the polarity sentence belongs in PROCESS.md where the filer reads it.
BOOTSTRAP: this story closes the sprint it was built in, like story-005 closing
itself. Cut per plan review, to Sprint 3: constraints promotion with caps.
Files: plugins/xp-plugin/scripts/sprint_close.py, plugins/xp-plugin/scripts/close.py (dispatch only),
plugins/xp-plugin/scripts/work.py (ids + resolve), plugins/xp-plugin/skills/sprint-close/SKILL.md,
plugins/xp-plugin/templates/retro.md, plugins/xp-plugin/PROCESS.md, docs/DESIGN.md,
tests/test_sprint_close.py, tests/test_work.py
AC:
- Given two records appended in the same second, Then each carries a distinct content-derived id, and the id of every one of the 53 legacy entries is derivable without backfilling the file (fault-inject with concurrent writers, as the plan review did — 48 appends, 48 ids)
- Given a resolution whose replacement falsifier reds now, Then the CLI REFUSES; given one that greens, Then it is appended as a record naming the resolved id — never an edit, because an edited record is the mutable state constraint 10 forbids
- Given a resolution ref matching zero or more than one entry, Then it refuses — one rule covering the typo, the stale id and the duplicate-body tie
- Given a resolved record, When the batch runs, Then it executes THE RESOLUTION'S falsifier, not nothing — so a wrong resolution reds later and the record reopens (fault-inject: resolve, then break the fix, assert the batch reds)
- Given a red falsifier anywhere in the corpus (work.md unresolved bug/debt, or archive.md), When sprint start runs, Then it ABORTS and re-files the red as a bug — with the red constructed in a fixture, never observed
- Given sprint start on any sprint, Then membership comes from the `### Sprint <id>` heading argument, and stories in other sprints are ignored — the naive "no story in plan.md is non-done" reading refuses forever, because Sprint 3 is [ready] right now
- Given sprint start completes, Then NOTHING under the data root changed except appended bytes to work.md — asserted structurally (old bytes are an exact prefix of new; no other file differs), so the property survives every future addition to the leg
- Given sprint start runs twice, Then the second run is a no-op beyond its own appends — the first live run WILL be re-run
- Given sprint land --dry-run, Then it prints the exact command list the real path executes, read from the same lists (bookkeep.render_land_preview's precedent: a preview that drifts certifies a plan nobody runs)
- Given the release PR is MERGED, When the post-merge leg runs, Then the version bump and the tag are cut on the MERGED TRUNK SHA and the sprint_branch key is retired — both in one leg, because a tag cut at PR-open names a commit that is not the release, and the review commits the PR exists to produce land after it
- Given a tag that already exists, or no `gh` on PATH, Then the leg REFUSES before anything moves
- Given the version source, Then it is the latest git tag (`git describe --tags --abbrev=0`), not xp-plugin's own plugin.json, which is meaningless in a consuming project
- Given the shipped prose, Then skills/sprint-close/SKILL.md names the broad review and the LLM security review as human steps, and PROCESS.md carries both the record lifecycle (id, resolution) and the polarity sentence — asserted as a red test, not a coherence pin
Verify: pytest -q tests/test_sprint_close.py tests/test_work.py
Close review: deep
Executor: (default)

## Milestone 2 — The close runs itself   [in-progress]
Goal: the sprint close is marshalled rather than hand-composed, the size budgets
are enforced by something anyone can run, and out-of-sprint work has a legal path
that does not move main by hand.
Done when: `close.py sprint 3` runs start → review → land → post-merge on this
repo with zero hand-composed review prompts and no hand-steps besides the human
judgment points, and the budgets are enforced by a command on every push.

### Sprint 3 — the close runs itself
PLANNED 2026-08-21. DESIGN §10 puts the Codex adapter + packaging here; it SLIPS
TO SPRINT 4 with the `--reviewer` override, which is that adapter's seam and not
a standalone want. Sprint-002 closed by finding defects in the close machinery
ITSELF — an unbounded re-review, and three resolutions of which two, then three,
did not cover their claims. A second harness on top of that buys blast radius,
not product. SIX stories against a cap of 6, and the smallness is deliberate:
two are `Close review: deep`, one breaches a file cap on day one, and Sprint 4
reopens the same files.
ADDED MID-SPRINT (Paul's call — the human schedules, agents record): story-017,
second in the running order. It is a RECOVERED DIRECTIVE rather than new scope
(note b6335017), and it lands in spawn.py, so it competes with nothing here for
the close component's headroom. Second because every remaining story runs through
the leg it fixes.
CUT AFTER ITS PLAN REVIEW: story-018 ([planned] as a spawn gate) rested on a false
premise I asserted without checking — spawn.py:299 is already a WHITELIST
(`if status != "ready": refuse`), so both of its ACs passed against HEAD and
tests/test_spawn.py:274 already covered the class. The review measured it rather
than reasoning about it. What was genuinely missing is smaller and different:
nothing ever WRITES [planned], and both misses this sprint were forgetting, which
a state nobody defaults to cannot catch. Done inline instead of carded — loud,
patch-scale, minutes: the template seeds [planned], spawn's refusal names the
likely cause, PROCESS.md states the transition.
CUT AT PLANNING (Paul's steer: keep it simple, agents have judgment, we do not
need to handle every corner case — note 33ff82cc): story-013 (constraints
promotion with char caps) as bookkeeping under constraint 3, since the plan
reviewer, the SessionStart size banner and the human are all already in that
loop; story-015 (escape hatches for three record-lifecycle wedges) because all
three are LOUD — the batch refuses and names the record — and PROCESS's finding
bar says loud + patch-scale is fixed in minutes or filed, never scheduled.
Simplicity won and Feedback lost; the bet is that judgment covers loud failures.
NOTES DISPOSED HERE, because never is a decision and not a backlog: f7dfec27 and
6ce977cd — the two unreachable branches in `cmd_land` are DELETED by story-014,
which part-funds its lines; `reports/` growing forever is DROPPED (a directory of
diffs on one machine, loud and cheap, nobody bitten). a1196cd6 (`blocking[]` has
no human override) — DROPPED as a mechanism: the override exists and is human,
the lead files a note and lands by hand, which is exactly what 012a round 4 did.
1e3aa69c (per-clone branch names) — DROPPED: post-merge retires `sprint_branch`
every release, so the key is per-sprint and lives on the branch it names, and the
harm it feared is already a refusal (story-005).

#### story-010 — size-ratchet   [done]
Context: DESIGN §9's budgets become a command. FIRST, not last: the close
component measures 1,041 of 1,100 today (close.py 490 + review.py 218 +
bookkeep.py 129 + sprint_close.py 204) and story-014 spends into that headroom —
the wall goes up before the spend, not as a post-hoc verdict on a merged story.
NO GITHUB ACTION, cut at plan review: it is a second copy of a gate pre-push
already runs, on a surface system.md declares no harness for, and it cannot be
executed before it merges (constraint 12, which has bitten twice). The only hole
it would cover is `--no-verify`, which CLAUDE.md already calls a values violation.
ONE COPY OF THE NUMBERS: ratchet.py holds the sub-allocation and DESIGN §9 keeps
the total, the rationale, the only-ever-lowers rule and the sacrificial-feature
order. Closes bug c2d7ffdf — but its falsifier asserts the digits are PRESENT in
CLAUDE.md and .xp/system.md, so deleting them REDS it: this story must `work.py
resolve` it with a replacement covering the stronger claim, or it wedges the
sprint's own close (found at plan review; it was a trap of my own making).
Size: ratchet.py lands in misc, measured 366 of 900.
Files: tests/scripts/ratchet.py, lefthook.yml, tests/test_ratchet.py,
CLAUDE.md, .xp/system.md, docs/DESIGN.md
AC:
- Given the repo within budgets, When ratchet.py runs, Then exit 0 printing the per-component MEASURED/cap table — a live number on every push, because the sprint-002 SIZE BREACH was an agent estimating against a stale one and a pointer does not fix that
- Given a fixture tree constructed OVER a budget, Then nonzero naming the budget and the overage (the guard fault-injected, constraint 2)
- Given a FIXTURE tree whose comments + docstrings exceed 20% of its Python lines, Then nonzero naming the density and the worst file — a fixture, not this repo, which sits near 17% and would green a do-nothing implementation
- Given the sub-budgets, Then a test asserts they sum to ≤ the total, so raising one requires lowering another — constraint 1's displacement rule made mechanical rather than promised
- Given lefthook.yml, Then pre-push runs ratchet.py (structural pin)
- Given CLAUDE.md and .xp/system.md, Then neither states a budget NUMBER (the falsifier matches the budget shape — `≤N lines/words` against a component name — not any digit: system.md:7 says "Python 3.11+"); both point at the command, CLAUDE.md's "DESIGN is the authority" line gains the budget clause, and c2d7ffdf is resolved with a replacement that reds if a number comes back
Verify: pytest -q tests/test_ratchet.py
Close review: standard
Executor: (default)

#### story-014 — the sprint close marshals its reviews   [done]
Context: SYMMETRY, not new machinery. The story close marshals its one review —
close.py builds a bundle, spawns the reviewer, receives {fixed,blocking,noted},
and carries EARLIER ROUNDS so a later round validates instead of re-deriving
(012b AC 9). The sprint close marshals nothing: sprint_close.py contains the word
"review" once, in a docstring. Measured at sprint-002's close: both prompts were
hand-composed, and when four fix-commits needed re-checking there were no prior
findings to bound the pass — an unbounded re-review, the loop this process exists
to avoid. The bounding mechanism is a MODE SWITCH (note bae0b87b): findings handed
in → validate each; none handed in → run the full pass.
A SEPARATE `review` LEG, not inside `start`: story-009's shipped contract is that
`start` is read-and-emit and idempotent, and a spawning, tree-touching `start`
breaks it. ONE LEG, TWO LENSES (`--lens broad|security`): same bundle, same report
shape. The sprint reviewer is REPORT-ONLY — and that is a MECHANISM here, not a
charter claim (see AC 2), because the plan-review found the claim unenforced.
Closes c9b48a66, whose own falsifier is the identifier grep constraint 11 forbids
and which THIS SPRINT'S CLOSE WILL RUN: the story must `work.py resolve` it with
AC 4's land-refusal test, the same trap story-010 carried for c2d7ffdf.
POINT, DON'T RESTATE (Paul): the comment rubric and the finding bar ship as pinned
copies for one stated reason — "build_bundle never sends PROCESS.md" — which is
one line of Python, not a fact. TEAMMATE.md keeps its copy: spawn inlines into a
fresh session with no bundle, so for that reader the premise holds.
Size: DENSITY BINDS BEFORE LINES DO. Measured after story-017: 19.84% against a
20.00% cap — about five comment or docstring lines plugin-wide. This story may add
at most ~30 comment+docstring lines across its whole diff; sprint_close.corpus()
alone spends 11 on one docstring, so the house style does not fit. Rationale goes
into TEST NAMES (constraint 9: a checkable claim becomes a test, where it rots
loudly), or funds itself by cutting stale prose in the four files it edits. Run
ratchet.py BEFORE the first commit and at the end — a density red found at pre-push
after 165 lines is paid in rewriting, not deleting. Deleting cmd_land's dominated
branch removes 3 comment-free lines, which RAISES density.
Component measures 1,041 and story-010 moves 150 from misc, so the cap is
1,250 with story-011 (+60-80) still to come. Plan-reviewed estimate +125-165, NOT
the +90-130 I first wrote: the enumeration omitted the land guards (~15-20) and
the resolutions section cannot reuse corpus(), which discards the original
falsifier at substitution (~15-20). Also deletes cmd_land's dominated `if not
rounds` branch (f7dfec27); the merge-conflict abort STAYS until story-011's plan
re-checks it, because that deletion and its gates are one decision.
Files: plugins/xp-plugin/scripts/sprint_close.py, plugins/xp-plugin/scripts/review.py,
plugins/xp-plugin/scripts/close.py, plugins/xp-plugin/scripts/bookkeep.py,
plugins/xp-plugin/scripts/work.py, plugins/xp-plugin/agents/sprint-reviewer.md,
plugins/xp-plugin/agents/story-reviewer.md, plugins/xp-plugin/skills/sprint-close/SKILL.md,
docs/DESIGN.md, tests/test_sprint_close.py, tests/test_close.py
AC:
- Given `close.py sprint <id> review --lens broad`, Then it spawns with a bundle (cumulative diff against `default_branch()` — NOT `integration_target()`, which under `release: sprint` returns the SPRINT branch, so the diff would be EMPTY and the reviewer would certify nothing; the fixture checks out the sprint branch, so a header-grep assertion passes over that empty diff, which is c9b48a66's own failure mode inside the story that closes it. Assert a known string from a sprint-branch commit appears in the diff section — never a hardcoded "main", which passes vacuously in a fixture and breaks a `master` consumer — constraints, system, the sprint's story cards) and records the report under a key a story cannot shadow. Fault-inject BOTH keys: construct a story literally named "sprint-3.broad" and assert its report path AND its marker path differ from the sprint's. The marker is the file land reads for rounds and blocking[]; scoping the report and not the marker hands the gate the collision the report just refused (constraint 10)
- Given a sprint reviewer that COMMITS, When the leg finishes, Then it REFUSES via `review.abort_text` and records nothing — capture head BEFORE the launch and record `shown_sha` as that head, not as post-run HEAD. close.cmd_review records post-run deliberately because motion checks bound what could have moved; copying that ordering into a leg WITHOUT them makes anything the reviewer commits count as reviewed and ride the release PR. Fault-inject with a stub that commits — a stub that never commits certifies nothing
- Given a SECOND review of the same lens, Then the bundle carries the prior findings labelled "validate that each was addressed; do not re-derive the diff" — read from the MARKER state, which is where close.py keeps rounds; reading `reports/` off disk would be a second source of truth. Construct the marker, not the report file
- Given NO recorded review at all, When sprint land runs, Then it REFUSES — the base case IS c9b48a66's claim, and a guard that fires only when a record exists greens the do-nothing path. Also refuses when the recorded review does not cover HEAD, EXCEPT where the whole delta is under .xp/ (Paul's call — resting on the retro diff having its own human review at triage, NOT on .xp/ being harmless, or the clause is later read as 'rule changes need no review'): retro, digest and plan-status commits always land after the reviews, so a strict rule forces a fresh broad AND security review at every close — the afbd01a3 wedge, where completing the close invalidates the review that permits it. Code motion is never exempt
- Given resolutions filed during the sprint, Then the bundle carries the LATEST per record with the claim and ORIGINAL falsifier it replaced, and `## resolved` blocks are FILTERED OUT of the raw work.md section — they are work.md entries, so shipping both hands the reviewer every superseded correction verbatim and invites the re-litigation the dedup exists to prevent. Three of three resolutions needing independent reading were caught by a READER, never by resolve()'s green-check (7df6b116, b9382e2d, 997c0c63)
- Given a batch falsifier that reds, When start runs, Then the full tier HAS NOT RUN — the tier command writes a sentinel; assert its ABSENCE after the refusal AND its presence after a green batch, because absence alone also passes an implementation that deleted the tier
- Given agents/sprint-reviewer.md, Then it is a DELTA, not a charter: report-only, the altitude line, the two lenses, the {fixed,blocking,noted} shape, and a POINTER to PROCESS.md which this story makes the bundle carry. At most 150 words against the ~80 freed from story-reviewer.md. Without this AC an opus executor models it on story-reviewer.md (712 words), whose first duty is "fix in the tree under review" — the contradiction the plan review rejected
- Given the leg run from the DEFAULT branch, Then it REFUSES — the story leg has this guard (close.py:186-192); without it the diff is empty and land pushes whatever branch HEAD is on
- Given sprint land, Then it guards HEAD COVERAGE ONLY and must NOT gain a "main moved since the review" clause: that is trunk motion, which is story-018's business, and a card whose first word is SYMMETRY invites exactly that wrong copy from close.cmd_land
- Given the story-reviewer bundle, Then it carries PROCESS.md and the charter points at it. The two pins are NOT two-into-one: narrow test_close.py:1357 to PROCESS ↔ TEAMMATE (whose copy stays), DELETE :1628, and add a test that the bundle carries the file. PROCESS.md itself states the finding bar twice, so "exists once" is false as written
- Given skills/sprint-close/SKILL.md, Then step 2 no longer tells a human to hand-compose the two reviews this story automates, asserted by the shipped-prose class in test_close.py — and the story is WALKED before close: `close.py sprint 3 review --lens broad --dry-run` in this repo, output read (constraint 12, bitten twice)
Verify: pytest -q tests/test_sprint_close.py tests/test_close.py
Close review: deep
Executor: claude/opus — the plan review's call and mine: a cross-module signature
change (report_path, marker_path), a marker-scoping subtlety, a motion guard that
must be added rather than reused, and a budget ledger. story-010 showed
sonnet/medium handling a five-file story well, but that story added one new module
and changed no shared signature.

#### story-011 — free mode (card-less close)   [ready]
Context: `close.py free start <slug>` cuts <user>/free-YYYY-MM-DD-<slug> off the
default branch and emits a diff-only bundle; review via the 008 pipeline leg;
`free land` opens the PR to main carrying the patch bump — a free close targeting
main IS a release (v0.2.1 rule, DESIGN §6). This is what makes small out-of-sprint
fixes legal at all: today they either wait for a sprint or move main by hand.
Carries 012b handback N2, because this is the next story to open close.py: a
reviewer that REWRITES HISTORY (reset --hard or rebase, then commit) passes all
four motion checks — its range shows only its own commits, authorship holds, .xp/
is clean — and land merges with the lead's story commits DROPPED.
Runs AFTER story-014, which also opens close.py and moves the `render_*` helpers
to bookkeep.py — so 490 is not this story's baseline; re-measure at its plan step.
Size: close.py is 490 today against constraint 8's hard cap of 500, and free mode
adds ~60-80. The extraction is NAMED, not promised: free mode becomes its own
module behind a ~2-line dispatch in close.py — the shape story-009 already set
with sprint_close.py, which costs nothing against the per-file cap and keeps the
component arithmetic honest.
Files: plugins/xp-plugin/scripts/close.py, tests/test_close.py
AC:
- Given free start on the default branch, Then the dated free branch exists and the bundle is emitted without a story card
- Given free land with a pipeline-received report, Then the PR to main carries the patch bump
- Given free land with no report, Then it refuses
- Given a reviewed head that is no longer an ancestor of HEAD, When land runs, Then it REFUSES — fault-inject by rewriting history in a fixture, never by asserting the merge-base call is present
Verify: pytest -q tests/test_close.py
Close review: deep
Executor: (default)

#### story-016 — the plan reviewer's duty to say no   [ready]
Context: Paul, at this sprint's planning: the simplicity challenge came from HIM,
not from the review. THE OBVIOUS DIAGNOSIS IS WRONG, and the round-2 review caught
it by reading the file I had not: plan-reviewer.md:52-54 ALREADY says "you have
standing to recommend dropping scope entirely — saying no is a Courage finding,
not an overstep", and check 4 already asks "what test demands this?". The reviewer
had permission and did not use it; what moved this session was the PROMPT, which
asked the simplicity questions directly. So the change is permission → DUTY, and
the honest position is that we are not sure the charter is the variable at all —
which is why the walk below has two arms and can tell us we are wrong.
The rubric does NOT go into the story-reviewer: a reviewer reading a merged diff
cannot cut a story, and plan time is the only moment the cut is cheap.
Depends on story-010 only for the agent-prose budget backstop.
REVISED AT ITS OWN PLAN REVIEW, which disclosed that it is the agent whose charter
this rewrites and named where its interests ran with and against each finding.
THREE OF MY FOUR NAMED CUTS WERE WRONG: DESIGN.md:106 names exactly three
plan-reviewer duties (sprint cap, Files-as-collision-declaration, runnable Verify),
and lines 22-24's examples are the charter's ONLY implementation of two of them.
Answered from use rather than theory: that review's own top two findings came from
walking those two clauses. My thesis was "teeth are the long concrete clauses, fat
is the short abstract ones" — then I cut the concrete examples and kept the
abstract question above them. LINES 22-24 STAY. The displacement instead: check 5
splits — (b) "really three stories" folds into check 4 with the duty, (a) the
sprint-cap count moves into check 1, which already checks the plan against declared
numbers. Six checks become five, funded by 52-54 (~18 words) and check 5's header.
ARM 3 IS DROPPED, confounded three ways and fatally by one: the charter says "Read
VALUES.md first", and a fixture copied outside this repo HAS no VALUES.md — arms 1
and 2 would get a dangling pointer while arm 3 got 230 words of values, and it
would win by having values at all. Paul's question (does inlining change what a
reviewer CATCHES or only what it CITES) is filed for Sprint 4 with the confound
named; its budget pays for the negative control.
THE ≤524-WORD CAP IS DROPPED: nothing enforces it (ratchet counts no prose; spawn's
cap covers agent FRONTMATTER only), the successor number is written nowhere, and it
contradicts this card's own displace-at-checks thesis three lines up.
Size: DISPLACE AT THE LEVEL OF CHECKS, not words — parity prices every word the
same, but a charter's teeth are its long concrete clauses and its fat is its short
abstract ones, so word-parity under time pressure deletes an example. Six checks
become five: the CUT duty folds into check 4 (Simplicity), which already owns the
question, and check 5 (Size) folds in with it because "a story that is really three
stories" IS a cut finding. Funded by named lines: 52-54 (the standing sentence,
~18 words — it becomes the duty), the first two examples at 22-24 which restate the
sentence above them (~22 words, keeping the third, which fired this round), the
five nouns at 32-34 trimmed to two (~12), and check 5's header (~10). Measured
before: 524 words, 6 checks. Do not touch 25-28, 58-60 or 12-13.
Files: plugins/xp-plugin/agents/plan-reviewer.md, tests/test_close.py, docs/DESIGN.md
AC:
- Given the plan-reviewer charter, Then check 4 carries the CUT duty — name the stories and ACs that should not exist, say what is lost by cutting each, rank the cut with the other findings — the file has FIVE checks where it had six, and its word count is ≤ 524 as a backstop. The check count is the load-bearing number; the card carries before/after so the plan reviewer can check it. NOTE, corrected at story-010's close review: ratchet.py measures NO prose word count — it owns the Python budgets only, and the 1,236-of-2,500 figure belongs to spawn.py's injection profile, whose own comment says 'reported, never enforced'. The word count is therefore a card-level check by the plan reviewer, not a CI one, and this story must say so rather than inherit a mechanism that does not exist
- Given tests/fixtures/overdesigned_plan.md — which MUST gain a NEGATIVE CONTROL, a story that should SURVIVE (story-014 or story-010 as carded) — COPIED outside this repo with VALUES.md, constraints.md and system.md beside it, every arm run as `claude -p` with the charter INLINED frontmatter-stripped and cwd inside that directory (a Task subagent's charter is loaded by the harness, so swapping the file mid-session may hand both arms the SAME charter, and two arms would silently be one) — the sprint header names both cuts and note 33ff82cc gives the reasoning, so an in-repo fixture is open-book — When a fresh plan reviewer is run against it under the OLD charter and again under the NEW, with the same prompt and no simplicity question in either, Then the new arm recommends cutting at least one story and the old arm does not. TWO ARMS OR NONE: a single green arm measures the prompt and certifies the charter, and if both arms cut, the diagnosis was wrong and we learn that for one extra spawn, which is what a falsifier is for
- Given a THIRD arm — new charter, same fixture, same prompt, but VALUES.md INLINED in the prompt rather than pointed at — Then its findings are compared with arm 2's, and the comparison is recorded whichever way it falls. The question is Paul's: prose telling an agent to read a doc may cause the file to be opened without making it binding, because a file an agent READS arrives as tool output (data) while charter prose arrives as instruction — a boundary this repo already draws in session_start.py, which wraps repo content as "not plugin instructions". MEASURED so far, and it is only half an answer: the round-1/2 reviewer did read VALUES.md (one Read, plus a wc -w) and named the five values 99 times. That shows the pointer causes the read, not that it binds. The counter-evidence is the lead: VALUES.md is injected verbatim into every lead session and the lead still built a guard it had cut minutes earlier (note 997c0c63), so presence is not the variable that moved — independence was. One extra spawn buys the difference between "changes what a reviewer CATCHES" and "changes what it CITES", and if it changes nothing the pointer stays and 230 words stay out of every prompt
- Given the walk, Then it is RUN under a reading pre-registered on this card and both transcripts recorded verbatim — the differential is a FINDING, not an AC, because "the new arm cuts and the old does not" is an outcome no implementation can make true, and at n=1 it occurs ~25% of the time under the null. Without the negative control the walk can red only against "nothing changed", never against "the new charter became trigger-happy" — constraint 2 applied to the experiment itself
- Given the test, Then it asserts the CHECK COUNT (five where six) — a count, not a token grep — and the card states plainly that this certifies a count and CANNOT certify the duty works; test_the_plan_reviewer_charter_asks_for_a_file must pass UNCHANGED as the behaviour-preserving proof
- Given the charter's "write your findings to a file and say where" (lines 58-60), Then it NAMES the durable location — `<data-root>/plans/<story-id>.md` (Paul's call — `reports/` is story-review reports keyed by story and round; plan findings get their own home, and it is where the plan itself lands if story-019 goes ahead) — because "say where" let each reviewer pick: this sprint's went to a session scratchpad under /private/tmp and a teammate invented `.xp/reviews/` inside the repo. Same words, one more fact
- Given acceptance, Then it is Paul reading the walk transcripts: agent prose has no harness (system.md declares CLI as the only surface) and this story's entire product is prose
Verify: pytest -q tests/test_close.py -k charter_has_five_checks — the THIRD spelling. `-k prose` selected story-010's test; `-k plan_reviewer_charter` substring-matches the existing test_the_plan_reviewer_charter_asks_for_a_file (measured, exit 0). Both earlier spellings were GREEN AT HEAD. Pre-registered red is exit 5, no tests ran
Close review: deep — raised by the plan review, not lowerable: the charter is a
default path that cannot be tested, every future plan review runs under it, and
CLAUDE.md makes plan review the gate on all multi-file work. Degradation is silent.
Executor: (default)

#### story-017 — the teammate spawn is live and durable   [done]
Context: A RECOVERED DIRECTIVE (notes 1de5317c, 452cf7a9, b6335017). At story-008's
close Paul directed that full `claude -p` output be captured, porting ../xp-agents'
`run_with_tee`. It had three properties — DURABLE, BOUNDED, LIVE. story-012a landed
durability and 012b boundedness, both by other means and both scoped to the
REVIEWER; liveness landed nowhere and the teammate leg got none of the three.
MEASURED at sprint-003: the first real teammate spawn was invisible until it exited.
REDIRECTED at its plan review, which happened LATE — this card was spawned without
one (note ec72dd8b) and the review found the headline change unshippable. Measured
against the installed binary, not reasoned about: `claude -p --output-format
stream-json` exits 1 with "requires --verbose". `stub_claude` accepts any argv, so
the suite would have gone green while every real spawn died. The teammate was
stopped with zero commits; its `teammate_tee.py` name is kept.
NO WATCHDOG, deliberately (spawn.py:201-204 argues a teammate legitimately outruns
any wall clock, and cmd_spawn's call site has no except, so a bound there kills a
running story and abandons its worktree). HONEST CONSEQUENCE, stated so this card
does not overclaim the way the directive it recovers did: liveness gives a human
the ABILITY to see a hang; it does not DETECT one. Detection stays "someone
notices", exactly as today.
ASSUMPTION, and Paul's to correct: spawns are launched THROUGH THE LEAD's Bash
tool, not from a human terminal, so "live" means the lead can read a growing file
mid-run. That is why stdout gets a compact line per event and the LOG gets every
line verbatim — the raw stream is a firehose of thinking blocks and tool results
(57 turns on story-010) and would land, truncated, in the lead's context.
Size: spawn.py measures 376 against constraint 8's per-FILE hard cap of 500, and
this adds ~90-150 — so the extraction is NAMED, not promised: the loop lands in a
leaf `scripts/teammate_tee.py`, the split ../xp-agents made for the same reason.
The close component is untouched; ratchet.py lands this sprint and will measure it.
Files: plugins/xp-plugin/scripts/spawn.py, plugins/xp-plugin/scripts/teammate_tee.py,
plugins/xp-plugin/TEAMMATE.md, tests/test_spawn.py, tests/test_close.py
AC:
- Given a teammate launch, Then argv carries `--output-format stream-json` AND `--verbose`, which that combination REQUIRES — fault-inject against the real refusal, not the stub: a stub that rejects stream-json-without-verbose must red the old argv and green the new. review.py passes "json" explicitly, so its argv is untouched
- Given review.py, Then it is UNCHANGED and `tests/test_close.py::TestReviewLeg` passes UNCHANGED — `run_agent` is shared and this story rewrites it, so the proof of a behaviour-preserving change to a shared function is the existing checks passing, which is why test_close.py joins Verify
- Given a running teammate, Then every line goes verbatim to a project-scoped log, flushed per line, and a COMPACT one-line summary per event goes to stdout — construct it: kill the child mid-stream and assert the log holds the lines emitted before the kill
- Given a re-spawn after a failed run, Then the log APPENDS under a `===== spawn <story> <iso-ts> =====` header — after a hang the forensic record IS the artifact, and truncating it is the one unrecoverable move
- Given a log write that fails mid-stream, Then the loop warns and KEEPS CONSUMING the stream — ceasing to drain deadlocks a healthy child on a full pipe. Testable because `tee_stream(lines, log_write, out_write)` is a pure function: inject a writer raising OSError on its second call, assert every line was still consumed, a warning was emitted, and the run completed. An implementation that lets OSError propagate reds on the first assertion
- Given stderr merged into the stream, Then unparseable lines are logged and skipped, and the ONLY error is the absence of a terminal `type == "result"` object — one hook warning must not fail a good run
- Given a completed teammate, Then spawn prints one closing line built from that result object (turns, duration, cost, is_error) — this is the parse's only consumer, and without it the parse is a helper with no caller
- Given a teammate that ends with a dirty tree, or with NO commits of its own, When the spawn finishes, Then it exits NONZERO naming what is uncommitted AND the two recoveries (commit by hand in the worktree, or `git worktree remove` and re-spawn). "No commits of its own" is HEAD-after-the-flip compared with HEAD-after-the-run: `trunk..HEAD` counts the [in-progress] flip and can never reach zero, so that spelling is vacuous by construction. Two injections: a stub that writes a file and exits 0, and the existing stub that writes nothing
- Given TEAMMATE.md, Then ONE bullet replaces the two that contradict each other: red first, commit green, the wall stands, and a blocked teammate still escalates. Paul's rule holds — you are not finished until every change is committed — but it keeps the `--no-verify` prohibition inside it, because an absolute obligation to commit with the only sentence forbidding the bypass deleted MANUFACTURES the pressure to bypass; and it carves out escalation, or a stuck teammate commits half-written code to satisfy the guard and buries the escalation. "Watch it fail" STAYS: the wall gates commits, not edits, so watching a test fail is a working-copy action fully compatible with committing green pairs — and TEAMMATE.md is the executor's only contract, so deleting it there while VALUES, PROCESS, CLAUDE.md and the story-reviewer charter all still assert red-first leaves four artifacts diverged and the property enforced by nobody
- Given tests/test_spawn.py:114 (`test_the_teammate_launch_is_not`), Then it is UPDATED to the new path rather than left passing over one the teammate no longer takes — a falsifier covering an abandoned path is constraint 11's complaint
Verify: pytest -q tests/test_spawn.py tests/test_close.py
Close review: deep — raised from standard by the plan review: pipe-blocking and
deadlock logic, a subprocess contract, a default path the stub cannot execute, and
a prose contract every future teammate runs under.
Executor: (default)

#### story-018 — coverage is about overlap, not motion   [planned]
Context: MEASURED THIS SPRINT, three times on one story. The review leg refuses
when trunk has moved ahead of the fork point, and land refuses when trunk moved
since the review — so ANY commit on the sprint branch invalidates every in-flight
story's review, including commits touching nothing the story touches. story-010
was reviewed three times: once refused on the fork point, once on the .xp/ guard,
once because the lead's own bug-fix commits moved trunk. That serialises stories
the sprint deliberately planned to be file-disjoint, and it turns the parallelism
worktrees exist to provide back into a queue.
THE GUARD CONFLATES TWO PROPERTIES: (a) the review covered the STORY's own
changes — essential, and what bug f1391db4 was actually about; (b) the review
covered the exact MERGE RESULT — much stronger, and the reason any motion costs a
round. (b) earns its cost only where the two diffs touch the same files, which is
where semantic conflict lives and where no later review makes the interaction
cheap to find.
THE RULE: review computes the story's diff from its fork point (it already does)
and stops refusing on trunk motion; land refuses only when trunk moved AND the
files trunk changed intersect the files the story changed, or when the merge
conflicts (which PROCESS already owes a round). Disjoint motion lands unreviewed
by neither party's choice — it was never in either diff.
REVISED AT ITS PLAN REVIEW, which found the rule INERT AS WRITTEN. `.xp/plan.md` is
contended by construction — spawn commits the [in-progress] flip inside the story
worktree, land puts [done] into the merge commit — so a naive intersection is
non-empty in exactly the scenario the card exists to fix, and AC 1 would have gone
GREEN anyway because the fixture's card names `Files: src/thing.py` and its story
branch never commits its own flip. EXEMPT `.xp/plan.md` ONLY, on its own terms — a
container of per-story records with no cross-record semantics. NOT the directory:
constraints.md is the rubric the review applied, config.yml holds the tier land
runs, system.md declares the surfaces the ACs execute at. My "already out of scope
for review" argument was laundered — PROTECTED_XP is a separation-of-powers rule,
and build_bundle demonstrably sends the card.
THE MERGE-CONFLICT BACKSTOP DOES NOT FIRE. Measured, three fixtures under git ort:
a lead editing the Context line ONE line below the status header conflicts;
rewriting the ACs FOUR lines below merges CLEAN AND SILENT — the review read the old
ACs, the merged card carries new ones, nothing fires. Conflict is a function of line
distance, not semantic sameness. Carve it out deterministically: the exemption does
NOT apply when the story's own card differs between the recorded trunk_sha and tip.
THE BIGGER FINDING — THE RULE DELETES THE ONLY EXECUTION OF THE MERGED TREE. Today
the fork-point refusal forces `git merge <trunk>` on the story branch, so land's
Verify and tier run on an INTEGRATED tree. Under the new rule they never do: land
runs Verify, then the tier, then merges. The named case is story-014's own declared
shape — A changes review.run's signature, B adds a call site in another file:
disjoint, clean merge, broken product, and no review reliably catches a call-graph
break. FIX, keeping the whole parallelism win: on ANY motion land TRIAL-MERGES and
runs Verify plus the tier on the merged tree (merge --no-commit --no-ff, run,
--abort on red — deterministic, no spawn, no round); a review ROUND is owed only on
overlap. That splits "something executed the merge result" from "someone reviewed
it".
THE 014 DEPENDENCY IS CUT: one sprint branch, one release, so there is no
parallelism to recover at sprint level. 014 builds HEAD-coverage motion-based; 018
narrows the story level only.
THE STANDING PRACTICE THIS RESTS ON, Paul's, and written down here because it
lived only in his head: we do not run stories in parallel whose file domains
overlap. Nothing checks it — DESIGN §11's cross-story collision check was never
built — so land's overlap test is ALSO the detector for that practice being
violated, and it must NAME the overlapping files rather than merely refuse.
DANGER, and the reason this card is not a two-line change: bug f1391db4's
resolution falsifier is `pytest -q tests/test_close.py -k "recorded_base or
bare_re_review or trunk_motion_DURING"` — the exact tests this story rewrites.
Gutting or renaming them silently empties a filed record's coverage while the
batch keeps reporting green, which is constraint 11's failure arriving through
the back door. The story must re-point that resolution deliberately, and
`trunk_motion_DURING` (a teammate pushing DURING the review window) is a
different case that STAYS.
LANDED BEFORE THIS STORY, and it changes the ground: the 5d7388fc + 37c0fb4e fix
moved the trunk-held check into the preflight, hoisted a `os.chdir(held)` above
BOTH merge arms, and put `git worktree remove` immediately before the branch
delete. THREE CONSEQUENCES FOR THIS CARD. (1) The trial-merge in F4 runs in the
tree holding trunk, not the story tree, and the story worktree still exists at
that point — deliberately, because the trial needs it. (2) `trunk_worktree` no
longer lives in close.py; it is `bookkeep.held_trunk_tree`, returning
(path, error). (3) The at-risk list grows by the six tests that fix added, all in
TestFixingReviewer: they assert the worktree survives every refusal, so a rule
that lands on motion must keep that true.
MEASURED THERE, AND IT DISPOSES HALF OF f7dfec27: the merge-conflict abort is
UNREACHABLE in local mode — any conflict requires trunk motion, the motion guard
at close.py:296 fires first, and re-reviewing to clear it requires merging trunk
in, which resolves the conflict. F4's trial-merge is what would make that path
reachable again, so this story owns the decision rather than story-011.
Size: close.py 489 of the 500 hard cap — FOURTEEN lines, and the extraction to
scripts/close/coverage.py is now mandatory rather than named; component 1281 of
1300 after a 50-line move from spawn priced to that fix's need; density 19.52% of
20.00%. Before this story: 1044 + 014's
125-165 + 011's 60-80 = 1229-1289 against 1250. The extraction is NAMED: the
coverage and motion guards move together into scripts/close/coverage.py — that path
deliberately, because ratchet.component_for matches any path part, so scripts/close/
counts against CLOSE (its sanctioned growth path) while a top-level
scripts/coverage.py lands in misc and launders 60 lines out of the component
without removing one. Rationale into test names, not docstrings.
AT-RISK TESTS, six not three: recorded_base (:1124) carries f1391db4's claim under
the new rule and must survive UNCHANGED as the substitute falsifier's core;
bare_re_review (:667) loses its purpose but carries a second claim — a guard whose
remediation does not work is a wall — so the overlapping arm must assert the refusal
CLEARS after merge and review; trunk_motion_DURING (:1277) stays, and overlap must
be computed against the tip recorded BEFORE the launch (state["trunk_sha"]) or its
ordering property is gone. Also flipping refuse->merge:
test_pr_mode_detects_origin_trunk_motion (:328),
test_local_trunk_motion_with_remote_present_refused (:364) — 012a round-4's guards,
one per ref — and test_tag_named_like_sprint_branch_cannot_freeze_the_guard (:545).
Compute on BOTH refs and inject on both.
THE RESIDUAL BET, stated so the rule is reversible if it bites: an interaction
neither the suite nor a conflict can see — two stories adding the same CLI
subcommand in different files, or the same key to the shared close marker. The
sprint broad review is the only remaining net.
Files: plugins/xp-plugin/scripts/close.py, plugins/xp-plugin/scripts/close/coverage.py,
docs/DESIGN.md, plugins/xp-plugin/skills/story-close/SKILL.md, tests/test_close.py
AC:
- Given trunk moved with a file set DISJOINT from the story's since the review, When land runs, Then it merges without a new round — fault-inject the pair: the same fixture with one OVERLAPPING file must refuse
- Given trunk moved touching a file the story also changed, Then land REFUSES naming the overlapping files — the message is the cross-story collision detector DESIGN §11 never built
- Given the review leg and trunk ahead of the fork point, Then it no longer refuses; the story's diff is computed from its fork point as today
- Given f1391db4's resolution, Then it is re-resolved against whichever tests survive, with the substitution covering the SAME claim (a merge whose recorded review never covered the story's own changes) — verified by construction, not by the batch going green
- Given DESIGN §6, Then it states overlap-not-motion, because the doc moves with the code or they disagree
Verify: pytest -q tests/test_close.py
Close review: deep
Executor: (default)

### Sprint 4
DESIGN §10's Codex adapter + packaging lands here, deferred from Sprint 3 with the
`--reviewer` override that is its seam.

#### story-019 — the execution plan is per-clone   [planned]
Context: A REAL USER REQUIREMENT, not a cleanup. Paul runs three clones of one repo
(../legacy, ../legacy2, ../legacy3 — one remote, one `develop`) each driving a
DIFFERENT workstream under xp-agents, each with its own execution_plan.json and
sprint.json in its own SMM dir: 'Tip Jar + Store Launch', 'Admin accounts &
analytics dashboard', 'Mobile mockup-fidelity depth', 'M6 Backlog Paydown'. He wants
xp-plugin to replace xp-agents there, and today it cannot: `.xp/plan.md` is one
in-repo file, so three streams would fight over it. The predecessor already drew the
line this story adopts — SHARED understanding of the system, PER-CLONE execution —
and Legacy's own CLAUDE.md says so: "this repo is worked in parallel clones".
NO NEW MECHANISM: `data_root()` hashes the git-common-dir, so three clones already
have three state roots and every worktree of one clone shares its clone's — which is
exactly the sharing a spawned teammate needs. The move is a path change.
WHAT STAYS IN THE REPO, because the split is not "everything moves": constraints.md
(three streams on one codebase obey the same rules, and a promotion in one binds the
others), config.yml (tiers, roles, caps), system.md (describes the SYSTEM, not the
work — xp-agents duplicated it per clone; in-repo is better and it barely churns).
COSTS, stated so they are decisions and not discoveries: (1) the plan stops being
git-versioned — measured on this repo, the CHANGELOG carries release narrative and
docs/retros/ the sprint narrative, but card-level deliberation (why 013 and 015 were
cut, why 014 moved behind 010, three estimate revisions) lives ONLY in commit
messages today, so PROCESS's "decisions go in work.md with the value tradeoff named"
becomes the sole record; (2) a fresh clone starts with no plan, correct for this
model but xp-setup must scaffold into the state root; (3) sprint membership and the
release become per-stream, which is coherent here and would not be under one shared
sprint.
SIDE EFFECT, deliberately not the justification: it dissolves the plan.md contention
that serialised sprint-003 — no story diff contains the plan, so no card edit
invalidates an in-flight review. story-018 should be re-read after this lands; its
plan.md exemption may become unnecessary.
Full proposed DESIGN §3/§4 diff drafted at <data-root>/plans/design-diff-plan-per-clone.md.
Files: docs/DESIGN.md, plugins/xp-plugin/scripts/{close,spawn,sprint_close,setup,session_start}.py,
plugins/xp-plugin/skills/xp-setup/SKILL.md, plugins/xp-plugin/PROCESS.md, tests/*
AC:
- Given two clones of one repo, When each writes a plan, Then neither sees the other's — fault-inject by constructing two repos with distinct git-common-dirs and asserting distinct plan paths, not by asserting the path format
- Given a worktree of a clone, Then it reads its CLONE's plan, not a per-worktree copy — the teammate must see the card the lead wrote
- Given `xp-setup` on a bare repo, Then the plan is scaffolded into the state root and `.xp/` holds only config, constraints and system
- Given a repo whose `.xp/plan.md` still exists (every project scaffolded before this), Then the tools REFUSE with a message naming the move rather than silently reading an empty plan — a silent empty plan is a sprint close that reports no stories
- Given DESIGN §3 and §4, Then the layout and the three stated costs move with the code
Verify: pytest -q tests/test_setup.py tests/test_close.py tests/test_spawn.py tests/test_sprint_close.py
Close review: deep
Executor: (default)
