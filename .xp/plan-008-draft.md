# Plan — story-008: close.py spawns the reviewer (completes Milestone 1)

## The change in one line
`close.py story <id> start | reviewed --verdict "..."` becomes
`close.py story <id> review | land` — the pipeline spawns the story-reviewer itself
and records its VERDICT line; no human-supplied verdict string survives.

## 1. close.py — leg rename and the reviewer spawn

### `review` (was `start`)
Preflight unchanged (dirty tree, .xp/plan.md present, status == in-progress, not on
trunk/default). Then:

1. Build the existing bundle sections, prepending a new first section: the
   story-reviewer charter, read from `PLUGIN_ROOT/agents/story-reviewer.md` with its
   YAML frontmatter stripped. Rationale: the reviewer runs as a *top-level headless
   session*, not as a subagent, so the agent file is not loaded by the harness —
   inlining it is the mechanism, the path is the fallback (spawn.py's rule).
2. Resolve the reviewer's model/effort via `spawn.resolve_role("reviewer")` — called
   with NO card, so the card's `Executor:` (the executor's model) cannot override the
   reviewer role.
3. Launch: `spawn.claude_argv(model, effort, "json")` + `spawn.run_agent(argv, cwd,
   prompt, role="reviewer", capture=True)`. Both imports are FUNCTION-LOCAL —
   spawn.py imports `integration_target`/`fail` from close.py at module level, so a
   module-level import back is a cycle.
4. Parse the captured stdout as one JSON object, take `["result"]`; print it (this IS
   the lead's judgment point — findings must be read).
5. Extract the verdict: the LAST line whose stripped form starts with `VERDICT:`.
   None found -> record `verdict: ""` and print a loud warning; `land` refuses later.
6. Marker gains `verdict` and `rounds` beside the existing
   `reviewed_sha`/`trunk_sha`/`origin_trunk_sha`.

`review` takes an internal delta mode: diff base is `reviewed_sha..HEAD` instead of
`merge-base(trunk)..HEAD`. Only `land` uses it.

### `land` (was `reviewed`)
Unchanged: dirty-tree refusal, marker-exists refusal, pr-mode-vs-sprint-target
refusal, trunk-moved refusal, Verify + story tier, merge with the verdict verbatim,
post-merge plan flip + amend.

New/changed:
- **No `--verdict`.** argparse drops the flag, so `--verdict` exits 2 with
  "unrecognized arguments" (AC 1's second half). Pinned by test, not by hand-rolled code.
- **Empty recorded verdict -> refuse** ("no VERDICT line was recorded — no verdict, no
  merge; re-run review").
- **Drift (HEAD != reviewed_sha):** instead of today's "go re-review by hand",
  land runs the review leg IN-PIPELINE on `reviewed_sha..HEAD`, increments `rounds`,
  re-baselines the marker (new sha + new verdict), prints the delta findings, and then
  REFUSES this land so the lead reads them and re-runs `land`. At `rounds >= 2` it
  refuses WITHOUT another review, naming the human (PROCESS's hard cap of two rounds).
- **Post-merge, local mode only:**
  a. Green the story's test-status markers: write `{"story": id, "verify": v, "red":
     false}` to every `*.{story_id}.test-status` in the markers dir. Reason: land runs
     Verify through `subprocess.run`, not the Bash tool, so no PostToolUse fires and a
     red marker from earlier in the session stays on disk as a false statement about
     measured state. Cross-session glob because land just measured green for that
     story on the tree that merged.
  b. `git push` the integration branch (the pre-push wall is the real check).
  c. `git branch -d <story-branch>` THEN `git push origin --delete <story-branch>` —
     that order is load-bearing and was measured at story-007 close: `-d`'s safety
     check compares against the branch's UPSTREAM ref, so deleting origin first forces
     a `-D` that throws away the merged check.
  d. b and c failing WARN (naming the exact command to run), they do not fail the run:
     the merge has already landed, and a hard exit there strands state with the marker
     already gone. The warning says the merge is local-only if the push failed.
  pr mode is untouched — `gh pr merge --delete-branch` already covers c.

### XP_ROLE guard
Top of `main()`, before anything else: refuse when `os.environ.get("XP_ROLE", "lead")
!= "lead"`. Broader than the AC's `teammate` (a spawned reviewer must not close
either), and it is the same predicate session_start.py already uses for the profile
gate. Fault-injected in test: same invocation passes the guard without the env var.

## 2. spawn.py
- `run_agent(argv, cwd, prompt, role="teammate", capture=False)` — `role` sets
  `XP_ROLE`; `capture` sets `capture_output=True`. Default args keep every existing
  call site byte-identical.

## 3. Story-scoped test-status markers (the carried sprint-001 triage input)
Today `bash_status.marker_file` keys on `sha1(verify)`, so two in-progress stories
with byte-identical Verify commands share one marker — story B's green hides story A's
red, which is exactly what constraint 10 forbids.

- `in_progress_verifies() -> in_progress_stories()` returning `[(story_id, verify)]`.
  (`stop_gate` imports the old name; it moves to the new one.)
- `invoked_verify(cmd, green) -> invoked_stories(cmd, green)` returning EVERY
  in-progress story whose Verify the command's overall exit entails — identical Verify
  strings entail both, so both get markers. Entailment logic itself is unchanged.
- `marker_file(session, story_id)` -> `{session}.{story_id}.test-status`; payload
  gains `"story"`.
- `stop_gate.red_verify_in_play` matches on the marker's `story` still being
  in-progress (was: its `verify` string in the live set); the block message still names
  the verify, which is what the lead can act on.

## 4. Prose
- `skills/story-close/SKILL.md`: steps 2–5 describe the manual spawn and the
  `--verdict` hand-off. Rewritten to the two-leg pipeline; the judgment point (step 3)
  stays, because it is the one thing the pipeline must not absorb (constraint 7).
- `close.py` module docstring: it currently advertises `start`/`reviewed --verdict`
  and says the hard property "arrives with the Sprint-2 spawn CLI" — that is this
  story.

## 5. TDD order (each red before its green)
1. `--verdict` is rejected as unknown; `review`/`land` are the only actions.
2. `review` launches the reviewer: stub `claude` on PATH records argv+stdin; assert
   argv carries `--plugin-dir`, the reviewer's model, `--output-format json`; assert
   stdin inlines the charter, the card, the diff, constraints, system.md.
3. `review` records the stub's VERDICT line into the marker verbatim.
4. Reviewer output with no VERDICT line -> `land` refuses, nothing merged.
5. `land` merges and the merge body carries the recorded verdict verbatim.
6. `land` greens the story's test-status marker (seed a red one first).
7. Drift -> `land` refuses AND a delta review ran in-pipeline (the stub's recorded
   stdin contains the delta commit and not the pre-review work), marker re-baselined.
8. `rounds` at 2 -> refuse naming the human, and NO third reviewer launch (assert the
   stub was not re-invoked).
9. `XP_ROLE=teammate` -> refuse; without it the same call gets past the guard.
10. Two in-progress stories, byte-identical Verify -> distinct marker files, and a red
    on story A survives a green on story B (test_stop_gate.py).
11. `land` pushes the integration branch and deletes the story branch local-then-origin
    (bare-repo origin fixture; assert the branch is gone from both, and assert the
    local delete happens first by asserting `-d` — not `-D` — succeeded).

## 6. Card amendment (flagging, not smuggling)
The card's `Files:` line names only close.py, spawn.py, tests/test_close.py. The work
above also touches bash_status.py, stop_gate.py, tests/test_stop_gate.py,
skills/story-close/SKILL.md. AC 5 (distinct markers) cannot be satisfied inside the
listed files at all. Proposal: amend the card's Files line to match, per the
"amending an already-scheduled card is not mid-sprint scheduling" rule.

## 7. Size
close.py is 342 lines against a hard cap of 500 (constraint 8) and the ≤800 close
sub-budget. Estimate after this story: ~460. If the green implementation lands over
500, the reviewer-spawn block (charter read, launch, parse, verdict extract) extracts
to `scripts/review.py` rather than being compressed — and story-009 already puts
sprint close in its own module, so the split is the established direction.
Known risk to call out: story-011 also lands in close.py.

---

# AMENDMENT (Paul, mid-review) — the close record

Section 6's card amendment is AUTHORIZED and already applied to .xp/plan.md: the
Files line now names bash_status.py, stop_gate.py, session_start.py,
skills/story-close/SKILL.md, tests/test_stop_gate.py and tests/test_session_start.py,
and Verify is now
`pytest -q tests/test_close.py tests/test_stop_gate.py tests/test_session_start.py`.

One NEW AC was added by Paul:

> Given land completes, Then close.py writes a deterministic CLOSE RECORD (story id +
> title, the recorded VERDICT line, merge sha, ISO stamp, and the next [ready] story
> from plan.md) and SessionStart injects it in the RECOVERY block — the layer that
> cannot go stale. close.py writes FACTS only; the narrative digest stays LLM-written
> (constraint 7 — deterministic Python may not summarize).

## Evidence that motivated it
- `session_start.recovery_block()` builds its story list with
  `if ln.startswith("#### ") and "[done]" not in ln` — it filters completed work OUT.
  So "what was just finished" exists only in `session.md`, the STALE-able layer.
- `session.md` is written BY HAND by the lead; close.py only prints a reminder string
  at the end of `cmd_reviewed`. That is a hand-step, and Milestone 1's done-when
  allows none besides the two judgment points.

## Planned shape
- New in close.py's `land`, post-merge: write `data_root()/last-close.json` —
  `{story, title, verdict, merge_sha, closed_at, next_ready}`. `next_ready` is the
  first `#### ... [ready]` header in the POST-merge plan.md. All five fields are
  reads or git output; nothing is summarized.
- `recovery_block()` gains a "last close:" line rendered from that file, placed with
  the other fresh-computed lines. Missing file -> the line is omitted, no error (the
  hook's existing degrade-to-silence posture).
- Tests: `land` writes the record with the verdict verbatim and the correct
  `next_ready` (test_close.py); SessionStart renders it, and renders WITHOUT it when
  the file is absent (test_session_start.py).

## What I want you to pressure, on top of the original list
6. Is `last-close.json` a project-global mutable marker, and therefore a constraint-10
   violation? It is one file per project, overwritten at every story close, NOT scoped
   by story or session. My argument that it is fine: it is a record of a completed
   past event rather than in-flight state, nothing reads it to make a decision, and
   scoping it per-story would defeat its only purpose (the next session does not know
   which story to look up). Tell me if that argument is wrong — constraint 10 says a
   project-global mutable marker is a DESIGN ERROR, with measured marker bleed behind
   it, and I may be rationalizing.
7. Does `next_ready` belong in a written record at all? plan.md is already injected
   fresh by the recovery block and is the authority — writing the next story into a
   file at close time creates a second copy that can disagree with plan.md the moment
   anyone reorders the sprint. Cheaper alternative: render `next_ready` at INJECTION
   time from plan.md, and keep only the completed-story facts in the record.
8. Does this AC belong on story-008 at all, or has 008 now grown past one story? It
   now spans: leg rename + reviewer spawn, marker re-scoping across two hook scripts,
   the XP_ROLE hard property, push/delete automation, AND this record. Say so plainly
   if the honest call is to split — the human has authorized the scope, but he
   authorized it on my summary, not on a size estimate.

---

# PLAN REVIEW — disposition (17 findings, 6 gating). All accepted; nothing escalated.

| # | Finding | Disposition |
|---|---|---|
| G1 | Reviewer runs `--dangerously-skip-permissions` in the LEAD's live tree, and `reviewed_sha` is read AFTER the launch — the drift guard can certify a commit the reviewer itself made | ACCEPT both halves: `--disallowedTools Edit,Write,NotebookEdit` on the reviewer launch (the measured instrument from the 05:27 note), AND capture HEAD *before* the launch, refusing after if HEAD moved or the tree went dirty |
| G2 | `rounds >= 2` cap deadlocks forever or is cleared by typing `review` — vacuous either way, and no AC asks for it | ACCEPT: dropped entirely. It also mis-mapped PROCESS's two-round cap, which is about contested findings, not HEAD movement |
| G3 | Greening another session's marker is a second writer forging a measurement (DESIGN §4: gate state is session-scoped, never a record), and it is redundant — `test_stop_gate.py:181` already proves the `[done]` flip releases the red | ACCEPT: close.py DELETES the story's markers instead. Card AC 3 amended — the old AC asserted something dishonest |
| G4 | The delta re-baseline must not rewrite `trunk_sha`/`origin_trunk_sha` — a trunk that moved during the review window would have its guard silently cleared | ACCEPT: delta path updates `reviewed_sha` + verdict ONLY |
| G5 | An unbounded verdict line enters `recovery_block`, and `session_start.py` truncates the TAIL — so a long verdict silently evicts constraints.md from the lead's profile | ACCEPT: cap the stored verdict at write time; the guard's test is that a 4,000-char verdict does not shrink the constraints section |
| G6 | `merge_sha` read before `--amend` names a commit on no ref | ACCEPT: record written last, after the amend; test asserts the sha equals `rev-parse <trunk>`, not merely that it exists |
| N1 | A delta verdict ("clean") overwrites round 1's "4 findings (1 gating)" in the merge body | ACCEPT: marker holds a verdict LIST; merge body carries every round, labelled |
| N2 | Warn-only push/delete reads as success; `git push origin --delete` misfires on this repo's own solo-close workflow (story-007's branch was never pushed) | ACCEPT: exit nonzero with a code distinct from the refusals; skip the origin delete when `refs/remotes/origin/<branch>` is absent |
| N3 | The `!= "lead"` widening is right but untested — the planned test passes identically against `== "teammate"` | ACCEPT: parametrize over teammate/reviewer/sprint-close/""; comment the bound the guard actually has (a teammate can still type `XP_ROLE=lead`) |
| N4 | `stub_claude` OVERWRITES one record file, so "assert not re-invoked" reads a stale record and passes vacuously; no handling for claude exiting nonzero / non-JSON / absent; capture means silence for a whole opus run; `--dry-run` would silently spawn a real session | ACCEPT all four |
| N6 | The SKILL.md rewrite touches the exact steps whose diff-base bug was just fixed in 9ab7eaa | ACCEPT: keep the integration-target sentence; the filed bug's falsifier stays green |
| N7 | Make the close record append-only | ACCEPT: `closes.jsonl`. Cheaper than defending the mutable-marker argument |
| N8 | Drop `next_ready` — and it can lie without any reorder, because spawn flips `[ready]`→`[in-progress]` inside the worktree, so trunk's plan.md still reads `[ready]` for a story being actively written | ACCEPT: dropped from the record |
| N9 | A corrupt close record blanks the WHOLE recovery block, since `build_all` try/excepts per builder | ACCEPT: try/except around the record parse INSIDE `recovery_block`; test with `{not json` |
| N10 | Nothing in Verify pins the reviewer's role | ACCEPT: assert `env["XP_ROLE"] == "reviewer"` in the test_close.py launch test — not by widening Verify |
| N11 | The extraction does not remove the import cycle | ACCEPT: `import review` stays function-local in close.py |

**Q8 — is 008 oversized?** Yes, and the reviewer showed it is not splittable: a new story is mid-sprint scheduling (and `sprint_cap: 6` is exactly met), and deferring AC 5 as debt is impossible because a debt's falsifier must be GREEN while AC 5's reds today — which makes it a bug, fixed now by definition. **The story stays whole; the FILE splits.** `scripts/review.py` is extracted in this story, unconditionally — it is code being written fresh here, so the extraction is free now and a real refactor later (story-011 lands in close.py this same sprint and would breach the 500-line cap).
