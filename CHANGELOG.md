# Changelog

Release notes started at v0.6.0; earlier entries are summarized from their
tag and merge messages. Full detail lives in the merge history and the
per-sprint review reports.

## v0.11.0 — commands are argv, handbacks are states

Sprint 10. Two stories, plus release-gate repairs found by the durable falsifier
ledger.

- `Verify:` is parsed once as one or more argv commands separated by unquoted `&&`
  and executed sequentially without a shell. Quoted arguments and chains remain;
  expansion, redirection, pipes, backgrounding, substitution and prose are refused at
  ready/review/land before any command runs. Existing cards that relied on shell
  syntax must move that logic into a script and name the script in `Verify:`.
- Executor handbacks now record explicit NEVER SPAWNED, RUNNING, STOPPED and FINISHED
  states. A clean completed story can be resumed by a fresh executor without deleting
  its worktree or branch; launch invalidates an old FINISHED credential by writing
  RUNNING, and a dirty FINISHED tree refuses. Handoff markers created before v0.11.0
  have no `state` and are refused until the lead discards/re-spawns or records a real
  STOPPED recovery—never forge FINISHED.
- This repository's subprocess-heavy fast tier caps xdist at eight workers. On the
  16-core dogfood box, `-n auto` took 135–253s; eight workers ran 934 tests in
  92–110s without weakening the existing 120s/150ms guards.
- Shipped source comments no longer cite project-local constraint numbers. A fresh
  consumer has its own constraint list, so the same index can name a different rule
  or nothing at all.

## v0.10.1 — what a consuming project hits on upgrade

Free patch. Both defects are consumer-facing and v0.10.0 shipped the first one.

- `constraints_size` refused an upgrading project on every commit and named no next
  action: v0.10.0 made `constraints_chars_cap` required, ships it only in the scaffold
  template, and setup never overwrites an existing config. The refusal now names the
  exact line to add. The policy is unchanged — an absent cap still refuses, as an
  unset test tier already does one function down — because defaulting it would impose
  a ceiling the project never chose and treating it as "no cap" would disable, on
  upgrade, the only enforcement that constraints still reach the lead.
- A `Verify:` line carrying backticks or `$(...)` is refused before ready, review and
  land instead of reaching `/bin/sh` as command substitution. Accepted lines keep the
  shell grammar every card relies on, `&&` chains included. This is the substitution
  half of GitHub #14 only: that report's `&&`-chain symptoms are still undiagnosed and
  the issue stays open.

## v0.10.0 — the profile fits the transport, and the sprint branch is per clone

Sprint 9. Five stories, two of them scheduled mid-sprint: one to unblock the close,
one on a bug that surfaced trying to run two sprints at once.

- A confirming sprint round is one story-shaped reviewer over the delta that can FIX
  inside its own round, not a scoped fanout that could only find. `named_paths` is
  deleted; round 1 keeps its four stages.
- The Sprint-8 Codex-lead walk is written down (`docs/AUDIT.md` §10), read from the
  recorded session rather than re-driven. It found that Codex truncates SessionStart
  hook output at 10,000 BYTES — head 4,916 + tail 5,084, identical across six samples
  — with no notice of its own and the middle removed.
- The lead profile is measured and capped in BYTES and now delivers every constraint.
  The digest, recovery block and sprint slice left the profile; `session_start.py
  recover` prints them on a tool channel with its own budget, and PROCESS.md's head
  names it. `constraints_chars_cap` is enforced by the scaffolded git wall.
- Each sprint-review stage resolves its own role (`finder`, `verifier`, `fixer`,
  `closer`), falling back to `reviewer` so a config predating the keys still runs.
- The sprint branch is recorded per clone in the state root, not in tracked config, so
  two clones can run two sprints; a stale tracked key refuses instead of retargeting
  a merge to trunk.

## v0.9.0 — completed work is kept, and the pipeline can close itself

Sprint 8. Four deliberately disjoint stories opened Milestone 4 by preserving work
that a completed leg had already paid for.

- Plan review now stops at its finding bar: addressable findings edit the executor's
  plan, while loud findings remain visible without forcing invented edits or another
  round. Sprint-slate and capacity judgment stay with the lead's card review.
- A sprint-review stage that refuses no longer erases the reports earlier stages
  wrote. The round records that it is incomplete, which stages actually reported,
  and the findings that survive; land refuses that truthful state.
- Pytest falsifiers using `-k` are rejected at filing. Live records were migrated to
  exact node IDs, so renames fail loudly instead of certifying an unrelated test.
- A spawned story can run the plugin copy in its future worktree, including resume
  and free-branch paths. Consuming projects without plugin sources keep the installed
  copy, and the handback tells the lead which root and version every close leg uses.
- Codex now receives this repository's conventions through `AGENTS.md`, which points
  to the shared `CLAUDE.md` rather than duplicating it.
- Sprint close now treats a retired card as terminal. The old done-only check called
  folded work unfinished and stopped this release; an exact regression test holds
  both the retired and active-state arms.

## v0.8.2 — a carded free patch lands where the free legs look for it

- A free patch WITH a card is now spawned onto the branch `free start` cut. Spawn
  derived its own name from the card title and branched from the integration
  target, so the executor's work landed where the free legs refuse it — and the
  lead's own commits on the free branch were absent from it, which made `reset`
  the obvious recovery and a silent way to lose them.
- The branch rule lives in `story_branch`, the one function both spawn and resume
  call, so a stopped free patch still resumes into its own worktree.
- Spawn now reports where that branch went: it says the tree CONTINUES the free
  branch rather than claiming it was cut off the integration target, it names the
  free review leg and the worktree to run it from — the story leg accepts a free
  id and writes the same marker free land reads — and if the lead is standing
  somewhere else, the refusal asks for `git checkout <branch>` instead of leaving
  `git branch -D` as the obvious way past it.

Bug 3dc03ed1 — a review losing its round to a file the lead left before it
started — is NOT fixed here. The attempted narrowing was inert: `close._preflight`
refuses a dirty tree before the reviewer launches, so the baseline is always empty
and the comparison collapses to the old check. Folded into story-054, where
recording the round from the artifacts already on disk is the shape that works.
Its plan-review twin needed no change: that leg compares the tree before and
after, so a file the lead left BEFORE it starts already costs no round, while one
left DURING it still refuses. Constructed both directions to check.

## v0.8.1 — three checks that could not red, and a record that stops growing

- Shipped comments no longer cite constraints by INDEX. Indices are project-local:
  `xp-setup` seeds a starter list and every project grows its own, so our
  "constraint 10" landed in a tree where 10 governs something else entirely.
- A plan review that produced findings is no longer reported as one nobody signed.
  Absent, unreadable and unsigned are three states; the notice enumerated two, and
  a consuming project lost a complete review to it.
- Report list caps now bound the DISPLAY, not the data. Past the cap, findings
  reached no verifier and the "(+N more)" placeholder was judged as if it were one.
- `work.py compact` moves disposed records' prose to `archive.md`, keeping their id,
  disposition and falsifier in `work.md`. The sprint-close corpus is unchanged —
  same falsifiers, same commands — and the archive is written and verified before
  `work.md` is touched. Measured on this repo: 528KB to 350KB.

## v0.8.0 — the harness cannot silently fail to do the work

Sprint 7. Milestone 3 closed: a consuming project ran a full sprint under released
versions and reported it (AUDIT.md §9), hand-steps named as the deliverable.

- A story-close round is refused unless the pipeline ran the card's Verify ITSELF,
  on the tree the round would certify. `blocking: []` used to be the reviewer's own
  word that Verify ran; a field report measured four rounds green with the build dead.
- The reviewer's bound is SILENCE, not a wall clock. A productive reviewer was
  killed twelve minutes after its last commit and the lead was told nothing happened.
  The refusal now names the live log, the salvage route, and `XP_AGENT_TIMEOUT`.
- A killed reviewer's round can be salvaged instead of re-bought.
- A confirming sprint round reads only its delta and re-runs only the finders whose
  paths moved, and the record says it was scoped rather than swept.
- Every leg that FINISHES names the next step, the way a refusing leg already did.
- Codex can spawn codex: DESIGN's "cannot on macOS" was measured against the wrong
  variable and is retired. Codex now runs as executor, nested plan reviewer, and
  story reviewer.
- Test fixtures copy a finished repository instead of rebuilding it: 16.97x on
  fixture cost, ~14% off the tier with six more tests.
- Constraint 12 now says prose that instructs an agent to run something is itself a
  path you must execute before shipping it.

## v0.7.7 — the fixer validates its own patch against the wall

- Both reviewer charters now tell the fixer to EDIT, STAGE, run the repo's commit
  gate over the INDEX, fix what it reports, then diff-and-restore. It still leaves
  the tree unchanged and still never commits, so the motion guard is untouched —
  but a patch that the gate would reject is now caught by the agent that wrote it.
  Staging is the load-bearing word: a commit gate reads the index, so over
  unstaged edits it checks nothing and greens.
- When the gate refuses anyway, the refusal names the gate, quotes the cause with
  ANSI stripped, says how much of the transcript it cut, and names the patch file
  that outlives the undo offered under it — instead of a colour-framed hook
  transcript with the reason twelve lines up.
- Field-reported by a consuming project: a formatter disagreeing about array
  wrapping discarded a whole sprint-review round, closer included.

## v0.7.6 — card review and plan review are two things with two owners

- The lead's review of the sprint slate is the **card review**; `spawn.py ready`
  is the lead's per-card commitment, not a review. The executor's review of its
  own implementation plan keeps the name **plan review**.
- PROCESS.md, TEAMMATE.md and CLAUDE.md now say the lead never writes an
  implementation plan. One word had covered both artifacts, and the lead read it
  as his — measured twice in one week.
- No script, CLI verb or gate changed. `plan_review.py` still serves both.
- AUDIT.md §9 records the field walk: a consuming project ran a full sprint under
  released versions, closing Milestone 3.

## v0.7.5 — one batch verdict, and no silent internal entry points

- Sprint close runs each distinct falsifier once and maps a red verdict back to
  every record that cites it, including the bug Claim it appends.
- Internal shebang-bearing modules refuse direct execution explicitly; the
  sprint-close refusal names `close.py sprint <id> <action>` as its public route.

## v0.7.4 — a leg that stops says so, and one that finishes finishes

- All three hooks share one advisory runner: malformed payloads and crashes remain
  exit-zero but print their traceback, and the terminal-input guard lives once.
- Free post-merge finds a spawned card by its keyed worktree, removes that tree
  and its recorded branch, then independently discharges the free branch.
- The Python cap rises once to 5,500 after the measured audit; exact component
  equality enforces the attributed 1,495/2,245/585/1,175 allocation.

## v0.7.3 — completed work reports itself completed

- Plan review accepts reasons preserved across hard wrapping while still
  refusing reasons absent under whitespace normalization.
- Free post-merge now uses story land's shared worktree teardown and branch
  discharge, reporting teardown failures after continuing cleanup.
- Hooks invoked from a terminal identify their JSON-on-stdin contract and exit
  instead of blocking; piped hook behavior is unchanged.
- `free start` reports whether its optional card already exists in the plan.

## v0.7.2 — the opt-out arrives before the default does

- **Codex sandbox posture is project-selectable.** `codex_sandbox` accepts
  `workspace-write` or `danger-full-access`; the latter remains the default, so
  an existing project gets byte-identical launch argv. Every Codex executor and
  reviewer reports the posture read back from its launched argv. Unknown values
  refuse before a worktree is cut, and `read-only` is refused separately because
  the plugin's roles must write their deliverables. Claude launches are unchanged.
- **Free work uses the same spawned-executor shape as stories.** PROCESS now
  names the path; `free start` refuses slugs whose 20-character truncation would
  detach an optional card, and its nudge places project-owned release artifacts
  before review without prescribing what those artifacts are.
- **A stopped story is taken over, not started again.** `spawn.py resume <id>`
  hands a stopped story's OWN worktree — its commits and its uncommitted work —
  to a fresh teammate, which is told plainly what it inherited and that it is not
  its own. Plain `spawn` still refuses a story that already has a worktree, so
  resume is an explicit verb and never a silent reuse. Before this, a stopped
  story could only be finished by hand or discarded along with its tree.
- The Python sub-budgets were re-cut twice, still totaling 5,000 lines: once to
  fund the close/free surface, then 70 lines misc-to-spawn for the resume work.
  Both were priced against measured occupancy.

## v0.7.1 — the sandbox we never chose, and the rules that never arrived

A patch, not a sprint. Three unrelated defects that each cost a consuming
project on day one, plus one the fix for the second uncovered.

- **Codex teammates and reviewers run unsandboxed.** Every codex leg now
  launches `--sandbox danger-full-access`, and every launch PRINTS the posture,
  read back off the argv actually used. Measured on 0.149.0 with controls:
  under `workspace-write` the Docker socket, loopback TCP and a nested
  `codex exec` are each denied, and one string lifts all three — `--add-dir`
  does not, it grants path writes, not socket-connect capability. This removes
  an inconsistency rather than adding a risk class: the Claude legs already run
  with no OS sandbox, because Claude Code exposes none. **Not yet configurable
  — story-040 owes the opt-out, and until it lands a project cannot decline.**
  Gone with it: the role-keyed `network` argument, which is how the REVIEWER leg
  came to run with no network at all — true, unprinted, and believed backwards.
- **The session digest is REPLACED, and something measures it.** Its size was
  stated in three places and its lifecycle in none, so ours grew to 380 lines
  and 26,797 chars over six sprints and silently evicted four constraints from
  the lead's profile. SessionStart now refuses over the bound, naming the path,
  the count and the bound.
- **The lead profile fits, and VALUES leads it.** `OUTPUT_CAP` 12,000 → 18,000,
  derived rather than aspirational. Order is now contract: VALUES first,
  PROCESS second, neither dropped nor moved. When the cap does bind, the notice
  names every rule it dropped — computed against `constraints.md`, never by
  scanning the cut region, because PROCESS.md carries four lines of the shape a
  constraint has.
- **README says how to launch a Codex lead.** A spawn happens inside the lead's
  own sandbox, so a confined Codex lead can nest neither `codex exec` nor the
  network a nested `claude -p` needs. The flag, and what a Codex lead gives up.
- The push wall re-runs lint and gitleaks, closing the `core.hooksPath` bypass;
  an unreadable session digest costs the digest, not the whole recovery block.

## v0.7.0 — the consumer's copy: what a project that is not us can see

Seven stories. The theme is everything a consuming project hits that we never
do, because we are the only user and our tests build their own fixtures.

- **A worktree's environment is torn down, not just unlinked.** `Worktree
  bootstrap:` has shipped since v0.6.2; teardown was a promise with no code, so a
  project whose bootstrap starts a container outside the checkout was handed an
  obligation nothing discharged. Teardown now runs inside the doomed checkout
  before removal, REPORTS and continues rather than refusing (a refusing teardown
  wedges every close), and gets a wall clock — `teardown_timeout:` in
  `config.yml`, so a project doing heavy lifting raises it rather than forking.
- **An aging config says so.** A `config.yml` scaffolded by an older `xp-setup`
  never gains keys the template adds later, and the refusal named the SHAPE it
  wanted rather than the cause. It now names the key, the file and the line to
  add — and distinguishes a key that is ABSENT because your config predates it
  from one that is MALFORMED because you typed it wrong.
- **Free mode is a one-card sprint.** `close/free.py` was 120 lines re-expressing
  `sprint_close.cmd_land` almost step for step; the duplication is gone, free
  inherits the release-ordering guard rather than taking a fourth copy of it, and
  the tag is cut on the merged sha instead of being a hand-step.
- **The plan review edits the plan instead of arguing about it.** The reviewer
  now writes its findings INTO the draft with their reasons, rather than handing
  them back to the party least able to concede them. Measured across this sprint:
  stories before the change took eight and nine plan rounds; the three after it
  took one each.
- **`spawn` refuses what it cannot read.** A missing `.xp/system.md` read as "no
  bootstrap line" and skipped; a present but non-UTF-8 one tracebacked. Both now
  refuse by name, and the refusal names a command that WORKS in that state — the
  first draft named one that refuses in exactly the state that produces it.
- **A respawned teammate inherits what stopped the last one.** An escalation used
  to cost the successor everything: it re-derived the plan and re-ran the review
  from scratch, though both survived on disk. It now receives its predecessor's
  draft, the findings that stopped it, and the record it filed — and the draft
  lands somewhere `git worktree remove` cannot destroy.
- **The reviewer proposes a patch; the script commits it.** Reviewers are
  read-only on every harness now and emit a patch beside their report;
  `close.py` applies and commits it under the reviewer identity. That retires the
  injected `GIT_AUTHOR_*` credential, the linked-worktree index write a sandboxed
  codex reviewer could not perform, and an after-the-fact authorship scan.
- **The push wall re-checks what a skipped commit hook would have caught.**
  `git -c core.hooksPath=<nonexistent> commit` runs no hooks and exits 0 — a
  silent equivalent of `--no-verify`. `pre-push` ran neither lint nor gitleaks, so
  a bypassed commit carried secrets to the remote. It now re-runs both: the ACT
  leaves no trace, but every gate here is a pure function of the tree, so the
  OUTCOME still can be checked.
- **Smaller, and consumer-facing:** a duplicated `Worktree` label is refused
  naming both lines instead of silently resolving to the first; a missing release
  manifest is reported as missing rather than unreadable; the reviewer's
  wall-clock refusal names `XP_AGENT_TIMEOUT`, the knob that moves it; records
  hold 4,000 chars and the session start names eight of them rather than three;
  and `PROCESS.md` names every skill it ships.

## v0.6.5 — a teammate that stops and says so is escalating, not failing

- **An escalation is no longer reported as a failed run.** `TEAMMATE.md` tells a
  blocked teammate to say so, file a note, and stop — and `spawn.py` then refused
  that exact handback ("the teammate made no commits of its own"), stranding the
  worktree for the lead to salvage by hand. Reported from the field at real cost:
  four runs, three with zero commits, two of them correct escalations, one
  carrying a plan three review rounds deep. A record filed during the run now
  turns that refusal into a reported escalation naming the records to read, the
  work left behind, and exit 3. A teammate that simply did not finish, and said
  nothing, is refused exactly as before — and a run that filed a record and then
  DIED is reported as that, with the harness's exit status, rather than as a stop
  it chose.
- **Python older than 3.11 now refuses by name instead of tracebacking.** Twelve
  of the thirteen shipped scripts died on 3.9 with `unsupported operand type(s)
  for |` — and `python3` on a stock Mac *is* 3.9. The README asked for 3.11+ and
  nothing enforced it, so a consuming project met a TypeError that named nothing:
  `setup.py` could not scaffold, and the SessionStart hook failed before its own
  "never break a session" guard could catch it. Now it says which interpreter it
  found and what it needs — on every entry point, including `plan_review.py`, the
  one leg `TEAMMATE.md` prints, which reached its own annotations first.
- **The v0.6.4 note that the Verify refusal "moved" to the mint was imprecise.**
  It was added at the mint and kept at land — one rule at two depths.

## v0.6.4 — the plan review survives the harness, and says so when it doesn't

- **The mandatory plan review now outlives the call that started it.** Two field
  failures, one per harness, on the same step. Under codex, a shell call's
  timeout is a per-call value *the model supplies* — ~10 seconds by default, and
  a teammate guessed 120s, lost, guessed 180s and lost again against a review
  that runs minutes. Under claude, a headless run ends when the model yields, so
  a teammate that backgrounded the review and yielded orphaned it. `plan_review.py`
  now detaches the review into its own session and waits on it; a call cut short
  loses nothing, and running it again rejoins the review in progress rather than
  starting a second one.
- **A review that dies reaches the lead.** The evidence of a skipped gate is an
  absence, and absences leave no artifact — so a marker is written at launch and
  cleared only when the review's own guards are satisfied. `close.py`'s review leg
  reports it to the lead and puts it in the story reviewer's bundle. Both field
  failures had been caught only by luck; one more commit and a story whose
  mandatory review never ran would have been accepted silently.
- **`unified_exec` is no longer disabled on codex spawns.** It was disabled to
  protect `PreToolUse`, and this plugin ships no PreToolUse hook — what binds a
  codex leg is `close.py` running Verify and the git-hook wall, neither reachable
  from `write_stdin`. An outdated bar with a measured cost.
- **A `Verify:` line whose commands are bulleted below it no longer reads as
  missing.** It parsed empty, indistinguishable from no line at all, and refused
  at *land* — after the story was written and reviewed — saying "has no Verify:
  line" about a card that visibly has one. The refusal moved to the credential
  mint, so an unverifiable card is stopped before a teammate is ever spawned, and
  the two states now say different things. The template that taught the form says
  the line is load-bearing, and a test feeds the shipped card to the real gate.

## v0.6.3 — one implementation of each rule, and room to work in

- **A missing plan reads the same at every leg.** Six commands answer "this
  clone has no plan", and `close.py story <id> land` had lost half of that
  answer — the half naming what to check. It is the leg reached last, so the
  story furthest along got the least help. All six now share one wording, and a
  test runs every leg against a plan-less clone and compares what they say.
- **Internal consolidation, no behavior change.** The status flip, the
  stream-JSON line decode and the record lookup behind `work.py resolve` /
  `archive` each had more than one implementation; they now have one apiece. A
  helper nothing called and a per-harness flag that was true for every harness
  are gone.
- **Budget re-allocation.** The hook layer was allocated 1,000 lines and
  measures 416, so 350 moved to the components that are actually growing. The
  5,000-line total is unchanged — this only corrects a five-sprint-old guess
  about where those lines would be needed.

## v0.6.2 — the bootstrap line the template taught was unreadable

- **`Worktree bootstrap:` is read past markdown emphasis.** `templates/system.md`
  bolds every field it teaches — `**Product**`, `**Stack**`, `**Layout**` — and
  the parser matched the literal substring `Worktree bootstrap:`, which a bolded
  label does not contain: the `**` sits between label and colon. It returned
  empty, and spawn's `if command := ...` skipped the block. No bootstrap, no
  warning, no nonzero exit — a teammate launched into a tree nothing prepared.
  Every repo that wrote the line in the template's own bolded style was
  affected; one written unbolded — the form every test used — was not.
- **An unreadable line now refuses; an absent one still doesn't.** Empty
  conflated "no line" (legitimate — a project may need no bootstrap) with "a
  line I could not read" (a defect), which is what made the above silent. `none`
  stays a legitimate no-op so the refusal cannot block a project that correctly
  has nothing to run. A parse failure refuses BEFORE the worktree is cut, or the
  corrected retry would hit `already spawned` and name the wrong problem.
- **Prose with two backticked spans no longer executes.** The value had to be
  one backticked command, but the match was greedy: the template's own example
  wording — `` `npm ci` or `uv sync` `` — matched end to end and ran verbatim
  under a shell, where the inner backticks are command substitution.
- **The shipped template is now exercised.** Every bootstrap test wrote its own
  unbolded line, so the form the template *teaches* had never once been fed to
  the parser — vacuous by fixture. A dogfood arm takes the template's own label
  verbatim, so a reformat reds here rather than in a consuming project.

## v0.6.1 — the wall stops reporting green having run nothing

- **The scaffolded wall refuses instead of warning.** `hook-lib.sh` had two
  paths that passed a commit having run nothing: a missing `gitleaks` warned
  and fell through, and an unset or still-`EDIT-ME` test tier returned 0. The
  second fired on a *freshly scaffolded* repo — setup seeds `EDIT-ME`, so the
  wall installed, the first commit passed, and no test had ever run. Both now
  exit 1 naming their next action. Reported from the field on a real monorepo.
- **A `#` inside a word is no longer read as a YAML comment.** `tier_cmd` cut
  the tier value at any `#`; YAML opens a comment only at a whitespace-preceded
  one. A tier carrying an inline env var whose password held a `#` truncated to
  a bare `VAR=value` — a valid shell command that assigns, exits 0 and runs no
  test. The same false green as the two legs above, reached from the parser
  instead of the guard. Trailing `  # ...` comments strip exactly as before.
- **`xp-setup` stops naming a hook it declined to write.** Where existing hook
  routing is found, the closing advice no longer says "add your linter to the
  pre-commit hook"; it names the actual task — point `.xp/config.yml`'s tiers
  at the existing wall's own commands, so the two cannot drift into different
  definitions of "fast".
- **`trunk:` — release where you actually integrate.** Sprint close targeted
  git's default branch with no way to say otherwise, so a repo integrating on
  `develop` could open a sprint, land stories, and then be refused at close for
  trying to tag a branch containing none of the sprint. `trunk:` in config.yml
  names where sprints land and releases tag; configured-but-absent refuses
  rather than falling back, since silently releasing to `main` is the failure
  it exists to prevent. Deliberately ONE branch — cutting `develop -> main`
  stays your release process, not xp's.
- **The release identity is now enforced, not just mandated.** v0.6.0 was
  tagged with the manifest still at 0.5.0; since the manifest version keys the
  consumer's plugin cache, that tag shipped the previous copy under a new name.
  `tests/test_release.py` refuses a manifest behind the latest tag, or a
  version with no CHANGELOG entry (constraint 14).

## v0.6.0 — either harness, any role (Sprint 5)

- **Headless plan review** (`plan_review.py`): the last subagent riding a
  harness tool became a config role — `harness/model/effort` like every other
  agent, launched through the shared runner. A codex teammate can now run its
  mandatory plan review (via a claude reviewer — see below).
- **Per-story `Reviewer:` card lines**, alongside `Executor:` — one card can
  say "author codex, review claude" and the next the inverse.
- **Every spawned agent streams**: one runner (`run_stream`) for teammates,
  reviewers, and plan reviewers — live tailable logs per role under the data
  root, native harness transcript pointers recorded, wall clocks preserved.
  Authored by codex (`gpt-5.6-sol`), reviewed by claude — the project's
  original pairing, now the default configuration.
- **The environment file** (`env.json` in the data root): setup seeds it,
  SessionStart refreshes it on both harnesses; processes nothing spawned
  (codex-lead scripts, hooks) resolve the installed plugin root through a
  validating reader that refuses stale or skewed installs loudly.
- **Codex sandbox facts, measured and shipped**: commits from linked
  worktrees need the git-common-dir widening (applied automatically,
  cwd-keyed); the executor leg gets sandbox network access (nested reviews
  need the API); codex cannot nest codex on macOS (upstream app-server
  limitation) — nested spawns route cross-harness by config.
- **`Files:` is a starting map, not a permission list**: implementations
  extend it and report deviations; an undeclared `.xp/` path remains a hard
  stop. (Measured cost of the old rule: ~500k tokens of plan-gate restarts.)
- Fast tier re-pinned at 55s for a doubled suite; 11 deep land-leg
  integration tests moved to the pre-push tier.

## v0.5.1 — free-mode patch release

- Duplicate story ids refuse instead of splitting across readers (the
  scaffold skeleton no longer collides with the natural first id). The first
  release shipped through `close.py free` — the card-less path to main.

## v0.5.0 — usable elsewhere, parallel here (Sprint 4)

- Per-clone execution plans; overlap-based land guards (trial merge, tier on
  the merged tree, ancestor and authorship checks); `[ready]` as a minted
  credential; one release review with angles (find → judge → fix → clear,
  security among the angles); codex as spawnable executor and reviewer with
  measured env-policy pins; codex as native lead (one hooks file, honest
  degradations); free mode.

## v0.4.0 and earlier

- The self-hosting core: story/sprint close pipelines, fixing reviewers,
  the git-hook wall, declarative records with falsifiers, the size ratchet.
