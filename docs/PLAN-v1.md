# The v1 cut — xp-plugin as a light touch

*Written 2026-10-04 at 3ad174c (v0.36.0). Self-contained: this is the design the cut builds
toward and the plan for making it. It supersedes DESIGN.md §3–§8 for everything it names;
DESIGN.md and AUDIT.md move to docs/history/ when the cut lands. Where this doc is silent,
VALUES.md decides.*

## 1. Goal

A plugin that gives a coding agent an XP process with a light touch: a card describing the
outcome, an agent implementing it, Git holding the work, independent fresh-context review,
and the project's own tests and release checks. Everything else is the agent's judgment,
guided by VALUES, JUDGMENT, the project's constraints and system notes.

Measured today: 13,486 shipped Python lines, 48,473 test lines, one story costs one planner,
three plan-review calls, two executors, three reviews and three suite runs. Targets for the
cut, measured per consuming-project story, not per line:

| Per story | Today | Target |
|---|---|---|
| Agent launches, happy path | 9 | 4 (planner, plan reviewer, executor, reviewer); 2 for a single-file card |
| Suite runs the plugin itself starts | 3 | 0 (hooks own them) |
| Lead CLI calls, slate to landed | 5 to 9 | 3 (`sprint open`, `story <id>`, `story land`) |
| Shipped Python | 13,486 | ≤ 4,000 (our cap; lives in CLAUDE.md) |

## 2. Principles

1. **Trust the agent on the spot.** The executor edits the card, extends Files, renames,
   restructures. The reviewer sees the result. No lock, digest, candidate or amendment
   protocol stands between an agent and plan.md beyond one append lock for parallel stories.
2. **State is what is on disk.** Card status in plan.md plus the files under the story's
   data directory. There are no markers, receipts, handoff JSON, checkpoints or fingerprints.
   Any command can be re-run; it continues from whatever exists.
3. **Hooks own routine checks.** Commit and push hooks run the project's tests. The plugin
   never runs a tier of its own and has no tier vocabulary. It runs exactly two things:
   a card's Acceptance on the tree that will merge, and the project's `sprint` hook at
   sprint land.
4. **A review is a fresh context reading an artifact and writing findings.** Two kinds:
   a plan reviewer reads a planning artifact (one card, or a slate); a diff reviewer reads
   a commit range (one story, or a sprint). The lead judges findings. A lead commit after a
   review never forces another review; land discloses the unreviewed range and the next
   review up (sprint review for a story, the human for a sprint) is the net.
5. **Hard properties live in git hooks or in the plugin doing the thing itself.** Merge,
   trial merge, version wall, tag. Nothing else refuses.
6. **Charters say what to read, what to produce, what you own.** Never how the mechanism
   around the agent works.
7. **Nothing under `plugins/xp-plugin/` exists for this repo's benefit.** Our caps and
   ratios live in CLAUDE.md.

## 3. The one cycle, three scopes

Every scope is plan → review the plan → do → review the diff → land.

| Scope | Plan artifact | Do | Diff reviewed | Lands on |
|---|---|---|---|---|
| story | one card | executor in a worktree | story branch since fork | sprint branch |
| sprint | the slate | the stories | sprint branch since trunk | trunk, tagged |
| free | one card | executor in a worktree | branch since trunk | trunk, patch tag |

A single-file card skips the planner and the plan reviewer: its plan is the card, and the
diff review is its net. A free patch is a story whose land target is trunk. A sprint's "do" is its stories.

## 4. Architecture

```
repo/.xp/
  config.yml         versioning, trunk, roles, version_files, debt_budget
  system.md          the project: stack, surfaces, conventions
  constraints.md     the project's rules; the plan reviewer enforces them
lefthook.yml (or .githooks/)   pre-commit, pre-push, sprint, nightly — the project's commands

~/.xp/data/<project>/
  plan.md            milestones, sprints, cards with [status]
  work.md            bug / debt / note records, append-only
  session.md         the lead's digest, written at every close
  landed.jsonl       one line per landed story
  stories/<id>/      plan.md, plan-review.md, review-N.md, agent logs
  sprints/<id>/      slate-review.md, review-N.md, release.json
  worktrees/<id>/
```

Deleted from the current tree: `markers/`, `evidence/` as a plugin concept, `reports/`,
`plans/*.round-N.*`, `*.handoff.json`, `*.ready.json`, `*.verify.json`, `runtimes/`,
`timing.jsonl`, `env.json` beyond the plugin root pointer.

## 5. Config

```yaml
# trunk: develop           # only when releases do not land on the default branch
versioning: off            # off: the project owns versions and tags; on: each release tagged
# version_files: package.json   # with versioning on; `none` tags without the wall
debt_budget: 0.2
roles:                     # harness/model[/effort]; a card's Executor: line overrides
  lead: claude/opus
  planner: claude/sonnet
  executor: claude/sonnet
  reviewer: claude/opus    # story diff reviews; pick a different family from executor
  # optional seats, falling back to their family: plan-reviewer (→ reviewer),
  # slate-reviewer (→ plan-reviewer), angle-reviewer (→ reviewer), fixer (→ executor)
```

`codex_sandbox` stays (decided during the build): a project has no other way to state a
Codex posture, and a role suffix would have to be repeated per role.

Gone: `release:` (stories land on the sprint branch, free patches on trunk; nothing else),
`tests:`, `full_legs`, `tier_coverage`, `tier_coverage_pins`, `preflight`,
`lifecycle_command`, `profile_target`, `constraints_chars_cap`, `teardown_timeout`, `review.verify_batches`, the seven
extra role seats.

## 6. Tests and acceptance

- **pre-commit** (scaffolded by setup): secrets scan, lint, the project's quick tests. The
  template says "under a minute; this runs on every commit" and leaves the command to the
  project. A hook refuses at run time while its command still reads `EDIT-ME`.
- **pre-push**: secrets scan, the project's broader tests.
- **sprint**: a named hook (`lefthook run sprint`, or `.githooks/sprint`) the plugin invokes
  once at sprint land on the trial-merged tree and once at post-merge if the merged tree
  differs. This is the release boundary and the only suite the plugin ever starts.
- **nightly**: a named hook the project wires to its own scheduler for the expensive tier.
  The plugin never runs it.
- **Acceptance** replaces `Verify:` on the card. It is one shell line, run from the repo root,
  that executes the card's acceptance criteria. Gherkin is the recommended form: the card's
  ACs are the scenarios, the feature file is the test, the Acceptance line runs it with the
  project's runner. A project without a runner names a test command. The executor runs it
  before handing back, the diff reviewer runs it, and land runs it on the trial-merged tree.
  Expensive scenarios carry a tag the sprint hook excludes and nightly includes.

Test commands live in exactly one place, the hook config. The plugin never restates them.

## 7. CLI: one entry point

`xp.py` replaces close.py, spawn.py, slate_review.py, plan_review.py, plan_acceptance.py,
work.py and session_start.py's command surface.

```
xp.py setup                       scaffold .xp/ and the hooks; refuses if .xp/ exists
xp.py recover                     print digest, card statuses, open records (SessionStart prints the command)

xp.py sprint plan <id>            fresh slate reviewer reads the slate, writes sprints/<id>/slate-review.md
xp.py sprint open <id>            cut sprint-<id>, record it
xp.py sprint review <id>          diff reviewers (one per angle) over trunk..sprint; one executor fix pass
xp.py sprint land <id>            version wall, trial merge, `sprint` hook, PR
xp.py sprint post-merge <id>      on trunk: sprint hook if tree differs, tag, release.json, clear branch

xp.py story <id>                  worktree, planner, plan reviewer, executor, diff reviewer; idempotent
xp.py story review <id>           one more diff review, on request
xp.py story land <id>             trial merge, Acceptance on merged tree, merge, [done], landed.jsonl

xp.py free <slug>                 branch from trunk, mint the card, then same as story
xp.py free land <slug>            as story land, target trunk, PR
xp.py free post-merge <slug>      patch tag

xp.py bug | debt | note | resolve records, with falsifier polarity run at filing
```

Every subcommand answers `--help` without doing anything. Every refusal names the next
action. There is no `amend`, `ready`, `resume`, `acknowledge-validation`, `salvage`,
`repair`, `judge`, `keep`, `archive`, `card-snapshot`, `edit-card`, `milestone-done`.

**Idempotence replaces resume.** `xp.py story <id>` looks at `stories/<id>/`: no plan.md →
run the planner; no plan-review.md (or one older than plan.md) → run the plan reviewer; no
handback.md → run the executor; no review-N.md recording HEAD as reviewed → run the reviewer;
otherwise print what exists and stop. A lead commit after a review reruns only the reviewer. A lead who edits the card and runs it again gets exactly the stages that are
missing. A lead who wants a stage re-run deletes its file.

## 8. The agents

Seven charters over four required seats (decided after the build: a charter written for
one artifact needs no "when given" clauses, and the orchestration is unchanged because
`bundle.prompt(role)` only picks a file). Each under 40 lines, three sections: read,
produce, own. VALUES and JUDGMENT are in the bundle, once: agents launch with `XP_AGENT`
set and no plugin dir, so the SessionStart injection stays silent for them on both
harnesses. constraints.md and system.md are passed in the bundle too.

- **planner** reads the card, the code and the tests; produces `stories/<id>/plan.md`;
  owns the implementation approach. Read-only on the repo.
- **plan reviewer** reads one card with its plan and the constraints; produces findings
  and edits the card and plan in place; owns correctness within the approved intent. A line beginning `QUESTION:` in the findings stops the story until the lead
  answers it in the card and deletes that line (or deletes the review file to have the plan
  re-reviewed against the answer). Read-only on the repo. No second round.
- **executor** reads the card, the plan, the findings; produces commits through the hooks;
  owns scope, Files, the card's wording and the Acceptance command. Runs Acceptance before
  handing back. Hands back with a short note: what changed, what deviated, what it could
  not decide. Reserved to the lead: title, Executor, anything a `QUESTION:` raised.
- **reviewer** reads a story's commit range, the card as spawned and now, and the handback;
  produces `review-N.md` with findings as fix / drop-with-reason / debt-with-both-bars; owns
  independent adversarial pressure, including fault-injecting any new guard. May commit
  fixes it is sure of, on the story branch, through the hooks. Reserved to the lead:
  anything it is not sure of.
- **slate reviewer** reads every card in a sprint's slate; produces findings and edits the
  cards in place; owns the slate's coherence: one outcome per card, true premises, size,
  order, collisions. Seat falls back to plan-reviewer, then reviewer.
- **angle reviewer** reads the whole sprint range under one angle file, with the slate and
  handbacks as context; produces findings at the seams between stories; commits nothing.
  Seat falls back to reviewer.
- **fixer** reads the merged angle findings; produces one commit per fix on the sprint
  branch and a handback naming each finding fixed, dropped or left to the lead; owns only
  the fixes it is sure of. Seat falls back to executor.

Sprint review is one angle reviewer per angle file, run in parallel; findings are merged;
the fixer gets one pass on the sprint branch; the lead judges. The finder, verifier, closer
and card-refresher stages do not exist.

## 9. Land

One function, three targets. Story and free: refuse to merge into the wrong target or with
a dirty tree; trial-merge the target in; run Acceptance on the merged tree; merge with the
reviews in the body, and any commits after the last review listed as "unreviewed:"; flip the
card to `[done]`; append landed.jsonl; remove the worktree. Sprint: version wall (tag,
manifest and CHANGELOG name one version), trial merge of trunk, `sprint` hook, PR. Post-merge
on trunk: rerun the sprint hook only if the merged tree differs from what land tested, tag,
`sprints/<id>/release.json`, clear the branch record.

Trunk overlap is a warning naming the files, never a refusal. Gate-file edits are nothing
special because there are no gate files: the hooks read the tree they run on.

## 10. Records and session memory

- `bug` requires a red falsifier, `debt` a green one plus both JUDGMENT bars, `note` is
  free text, `resolve` substitutes a green falsifier. The polarity check runs the command.
  That is the whole of work.py.
- The lead writes `session.md` at every close: intent, surprises, next step, under 30
  lines. `xp.py recover` prints it, then every non-done card's title and status, then open
  bugs and debts. That is the recovery block. Nothing else needs recovering because nothing
  else is state.

## 11. What is deleted, by file

Start pipeline: `spawn/ready.py`, `spawn/handoff.py`, `spawn/completion.py`,
`spawn/resume.py`, `spawn/handback.py`, `spawn/card_profile.py`, `plan_acceptance.py`,
`plan_confirmation.py`, `plan_disposition.py`, `plan_writer.py` (one append lock survives
in `work.py`), `card_text.py`, `bookkeep.py` except fork-point.

Close pipeline: `close/verify_log.py`, `close/verify_receipt.py`, `close/review_validation.py`,
`close/review_sequence.py`, `close/sprint_review_resume.py`, `close/review_artifacts.py`,
`close/finding_triage.py`, `close/falsifier_batch.py` (`recover` prints open records
instead), `close/tier_legs.py`, `close/sprint_coverage.py`, `close/sprint_state.py`,
`close/sprint_bundle.py`, `close/overlap.py` except the trial merge, `close/stages.py`,
`close/milestone.py`, `close/lifecycle.py`, `close/preflight.py`, `close/session_detail.py`,
`work/finding_judgment.py`, `work/disposal.py` except resolve, `review_report.py`,
`review_scope.py`, `work_compact.py`, `timing.py`, `log_rotate.py`.

Prose: `agents/sprint-reviewer.md`, `agents/slate-reviewer.md`, the five SKILL.md files
rewritten to a paragraph each pointing at `xp.py --help`, EXECUTOR.md rewritten as the
executor charter above, PROCESS.md rewritten from §3 and §7 of this doc.

Tests: every test file whose subject is deleted goes with it, unread. Tests of kept
behavior are kept and must pass unchanged where the behavior is unchanged.

Kept and trimmed: `teammate_tee.py` (the launcher and its liveness), `review_runner.py`
(detached launch for Codex shells), `env.py`, `git_source.py` to fork point only,
`session_start.py` to injection and the recover command, `setup.py`, `close/release.py`
(the version wall), `close/land.py` as §9, `review.py` to reviewer-motion guard and bundle
building, templates, `angles/`.

## 12. How the cut is made

On one branch, by hand, outside the sprint machinery, because the machinery is the subject.
The commit hooks stay on. This is a values decision recorded in the first commit body, not
a bypass. In order:

1. `git switch -c v1-cut`. Delete the files in §11 and their tests. Commit.
2. Write `xp.py` as the single entry point over the kept modules. Reconnect: story spawn
   as §7's idempotent walk, land as §9, sprint plan/review as §8. Commit per piece.
3. Rewrite the four charters, EXECUTOR.md, PROCESS.md, the five skills, `templates/`.
4. Write new tests only for hard properties: trial merge runs Acceptance on the merged tree,
   version wall refuses a mismatch, idempotent spawn runs only missing stages, record
   polarity. Fault-inject each.
5. Walk one story end to end on Claude and one on Codex in a scratch consumer, then the
   same in legacy. Fix what the walk finds. Walking is the acceptance; it is not optional.
6. Measure §1's table. Update CHANGELOG, bump to 1.0.0, tag. Move DESIGN.md and AUDIT.md to
   docs/history/. Install in legacy and divineruin; delete their `tests:` blocks and extra
   roles; their hooks already read their own commands.

Estimated four working days. The risk is drag from the kept tests, not design; the
mitigation is step 1 deleting test files whole.

## 13. Our rules, for CLAUDE.md and .xp/constraints.md (not the plugin)

- Shipped Python ≤ 4,000 lines, tests ≤ 2× shipped, enforced by `tests/scripts/ratchet.py`
  as a pre-commit wall, not a report.
- Replace constraint 2 with: fault-inject every hard property. Advisory behavior gets no
  guard and no test.
- New constraint, displacing 15: a field failure is answered first by deleting a mechanism.
  A card that adds one states why deletion cannot fix it.
- Retire constraints 11, 13's "promoted note" clause and 14's test reference as obsolete
  with the deleted machinery; the version wall stays as the one sentence in §9.

## 14. Open questions for Paul

1. Gherkin: recommend, or require? Legacy has 35 feature files; divineruin has 3. The doc
   recommends and leaves the Acceptance line as a command.
2. Reviewer commits: the diff reviewer may commit fixes it is sure of (§8), which makes the
   fixer role unnecessary. Alternative is a strictly read-only reviewer and one executor fix
   pass. The doc chooses the former for fewer launches.
3. Version number: 1.0.0 signals the break. Consumers finish in-flight sprints on 0.36.0
   first, since no state is migrated.

## 15. Constraints: the template caused the test bloat

Measured 2026-10-04:

| Project | Source | Tests | Ratio | Gate/meta scripts |
|---|---|---|---|---|
| legacy | 169,366 | 285,011 | 1.7x | 376 (71,748 lines) |
| divineruin | 78,910 | 173,641 | 2.2x | 22 (3,680 lines) |
| xp-plugin | 13,486 | 48,473 | 3.6x | — |

Three template items compound: "fault-inject every guard" (1), "tests are production code"
(2), "keep states distinct, test refusal boundaries" (10). Together they say every check
earns a check. Legacy's own constraint 1 grew a five-way taxonomy of vacuous guards and its
8 mandates a meta-test per gate change; divineruin's 12 requires every absence check to
prove its corpus non-empty. Each is a faithful application of the template.

Two other template items restate what the plugin or a hook already enforces, so they are
second copies: 6 (independent challenge, the plugin's job) and 9 (one release version, the
version wall). Delete both from the template.

### New `templates/constraints.md`

```
# Constraints

Reversing one of these makes it a different project. Cap: 10 items; adding one
retires one. Reviewers enforce these and cite the item. A rule a hook or the
plugin already enforces is a second copy: delete it.

1. **Test behavior at the outermost boundary that reaches it, once.** When an
   integration or acceptance test covers a behavior, delete the unit tests that
   duplicate it. Unit tests are TDD scaffolding, not a permanent asset.
2. **Tests cost what code costs.** Test lines stay at or below twice the lines
   they test. The commit hook finishes in under a minute; everything slower runs at
   push, at sprint close, or nightly. A slow test is a defect in the test.
3. **A guard is fault-injected once, when it is added, in its own test file,
   and only if its failure would be silent or corrupting.** No tests of tests,
   no meta-tests of gates, no proof that a check's corpus is non-empty. A loud
   failure needs no guard at all.
4. **Small files: target 300 lines, hard cap 500, tests included.** Extract,
   do not scroll.
5. **Comments carry only what a test or a name cannot**: the why, an external
   constraint, a rejected design. Restates the code or narrates history: delete.
6. **Fail fast, fail loud.** Raise instead of returning None or empty; no
   fallback that masks a defect.
7. **Run it before you write it down.** A plan, card, review or decision that
   claims what code does has read or executed that code first.
8. **Walk every shipped path before release.** A test fixture does not verify
   a user-facing or agent-instructed path; execute it end to end.
```

Eight items, ~1,400 characters. Project-neutral. Items 1 to 3 are the new ones; 4 to 8 are
the surviving originals. Removed: 1 (replaced by 3), 5 (folded into 1), 6, 9, 10.

### Per-project edits (cards for each project's next sprint, not ours)

**legacy**
- Replace 1 with template 3. The five-way taxonomy is the bloat engine.
- Replace 7 with template 2.
- In 8, keep "a gate that cannot run must FAIL" and the redaction rule; delete the
  meta-test mandate, the Verify/tier/refresh mechanics (that vocabulary leaves the plugin)
  and the population-derivation paragraph (that is item 7's "run it").
- Add template 1. Retire 5 (name things well) and 6 (boundaries) to make room; both are
  folded into 1 and 5.
- Keep 9 to 15 untouched: they are the product, not the process.
- One card: delete `scripts/test-*.sh` where the gate it tests has its own test, and merge
  the rest into the gate. 376 scripts is a suite about the suite.

**divineruin**
- Replace 1 with template 3.
- Delete 5 (falsifier shape belongs to JUDGMENT, which the plugin ships).
- In 7, keep "names both sides"; delete every sentence that names Verify, a tier, or
  `test:all`. That is config, not a constraint.
- Trim 12 to its first sentence, then delete it when 3 lands; it is the non-empty-corpus
  rule template 3 forbids.
- Add template 1 and 2. 11 and 10 stay; 9 stays.

**xp-plugin** (CLAUDE.md and `.xp/constraints.md`): §13 above, now derived from this
template rather than hand-written: 2 is the 2x ratio and the ratchet wall, 3 replaces our
constraint 2, and 11, 13 and 15 retire with the machinery they described.

### Cut procedure addendum

Step 6 of §12 gains: ship the new template; install in each consumer and apply the edits
above as that project's first card on the new plugin, with its ratchet number recorded in
the card so the next sprint can see the ratio move.
