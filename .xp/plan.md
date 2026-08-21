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
not product. FOUR stories against a cap of 6, and the smallness is deliberate:
two are `Close review: deep`, one breaches a file cap on day one, and Sprint 4
reopens the same files.
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

#### story-010 — size-ratchet   [ready]
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
Files: plugins/xp-plugin/scripts/ratchet.py, lefthook.yml, tests/test_ratchet.py,
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

#### story-014 — the sprint close marshals its reviews   [ready]
Context: SYMMETRY, not new machinery. The story close marshals its one review —
close.py builds a bundle, spawns the reviewer, receives {fixed,blocking,noted},
and carries EARLIER ROUNDS so a later round validates instead of re-deriving
(012b AC 9). The sprint close marshals nothing: sprint_close.py contains the word
"review" once, in a docstring. Measured at sprint-002's close: both prompts were
hand-composed, and when four fix-commits needed re-checking there were no prior
findings to bound the pass — an unbounded re-review, the loop this process exists
to avoid. The bounding mechanism is a MODE SWITCH (../xp-agents
xp-code-reviewer.md:18-19, note bae0b87b): findings handed in → validate each;
none handed in → run the full pass. We have it at story level already.
A SEPARATE `review` LEG, not inside `start`: story-009's shipped contract is that
`start` is read-and-emit and idempotent ("run twice → the second is a no-op
beyond its own appends"), and a spawning, tree-touching `start` breaks it. This
is DESIGN §6's split-review-from-commit at sprint level, the same split 012a made
at story level. ONE LEG, TWO LENSES (`--lens broad|security`): same bundle, same
report shape: two pipelines and a charter that does not exist yet is machinery.
The property worth keeping is that the report is RECORDED — three were lost to
stdout in one session. The sprint reviewer is REPORT-ONLY; a fixing reviewer here
would inherit 012b's whole apparatus (motion checks, authorship gate, abort path)
unscoped against a whole-sprint diff.
Closes bug c9b48a66. Also deletes the two unreachable `cmd_land` branches
(f7dfec27, 6ce977cd), which part-funds its lines.
Size: 59 lines of component headroom (1,041 of 1,100) against an estimated
+90-130. Either the named extraction — close.py's `render_*` helpers move to
bookkeep.py, their home — covers it, or the story carries a DESIGN §9 diff moving
100 from misc (366 of 900); story-010's sum assertion makes that zero-sum, and
constraint 1 says it moves by reviewed diff, never by discovery at the keyboard.
Files: plugins/xp-plugin/scripts/sprint_close.py, plugins/xp-plugin/scripts/review.py,
plugins/xp-plugin/scripts/close.py, plugins/xp-plugin/scripts/bookkeep.py,
plugins/xp-plugin/scripts/work.py, plugins/xp-plugin/skills/sprint-close/SKILL.md,
docs/DESIGN.md, tests/test_sprint_close.py
AC:
- Given `close.py sprint <id> review --lens broad`, Then it spawns the reviewer with a bundle (cumulative diff main...HEAD, constraints, system, the sprint's stories) and records the {fixed,blocking,noted} report under a key that cannot collide with a story's report file
- Given `--lens security`, Then the same leg, bundle and report shape are used with the security lens, and its report is recorded beside the broad one
- Given a SECOND review of the same lens, Then the bundle carries the prior findings labelled "validate that each was addressed; do not re-derive the diff" and the reviewer reports per-finding outcomes — fault-inject: construct a round-1 report and assert round 2's bundle contains its findings
- Given NO recorded review at all, When sprint land runs, Then it REFUSES, and separately when a recorded review's coverage does not include HEAD. c9b48a66's claim is that a PR can open over UNREVIEWED commits, so the base case IS the claim — a guard that fires only when a review record exists greens the do-nothing path and satisfies a carelessly worded AC (story land has `if not marker.exists(): refuse`; this is its twin)
- Given resolutions filed during the sprint, Then the bundle carries the LATEST per record with the claim and original falsifier it replaced, and a test pins `corpus()`'s last-wins substitution, which is undeclared and untested today — 4687f4b2 already carries three resolutions, so "each" would hand the reviewer two superseded corrections and invite re-litigating a fix already made. THREE OF THREE resolutions needing independent reading were caught by a READER, never by resolve()'s green-check (7df6b116, b9382e2d) — this is the only mechanism in the sprint that has already fired, and the argument against building any further check into resolve()
- Given a batch falsifier that reds, When start runs, Then the FULL TIER HAS NOT RUN — assert by construction (the tier command writes a sentinel; the sentinel is absent after the refusal), not by a cheapness predicate, which would be judgment in deterministic code. Sprint-002 spent 256 tests to refuse on a grep
Verify: pytest -q tests/test_sprint_close.py
Close review: deep
Executor: (default)

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
Files: plugins/xp-plugin/agents/plan-reviewer.md, tests/test_ratchet.py
AC:
- Given the plan-reviewer charter, Then check 4 carries the CUT duty — name the stories and ACs that should not exist, say what is lost by cutting each, rank the cut with the other findings — the file has FIVE checks where it had six, and its word count is ≤ 524 as a backstop. The check count is the load-bearing number; the card carries before/after so the plan reviewer can check it, and ratchet.py keeps enforcing only the aggregate agent-prose budget it already owns (1,236 of 2,500 today, not binding here)
- Given the over-designed draft from this sprint's planning (story-013 and story-015 as first written), extracted to an ISOLATED fixture file so the repo's later history is not reachable — the sprint header names both cuts and note 33ff82cc gives the reasoning, so an in-repo fixture is open-book — When a fresh plan reviewer is run against it under the OLD charter and again under the NEW, with the same prompt and no simplicity question in either, Then the new arm recommends cutting at least one story and the old arm does not. TWO ARMS OR NONE: a single green arm measures the prompt and certifies the charter, and if both arms cut, the diagnosis was wrong and we learn that for one extra spawn, which is what a falsifier is for
- Given the walk, Then its outcome is recorded in work.md with the reviewer's own words, both arms, including the outcome where the diagnosis is refuted
Verify: pytest -q tests/test_ratchet.py -k prose
Close review: standard
Executor: (default)
