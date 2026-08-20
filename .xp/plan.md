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

#### story-004 — Stop advisory gate   [in-progress]
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
