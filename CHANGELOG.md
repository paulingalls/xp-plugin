# Changelog

Release notes started at v0.6.0; earlier entries are summarized from their
tag and merge messages. Full detail lives in the merge history and the
per-sprint review reports.

## v0.6.5 — a teammate that stops and says so is escalating, not failing

- **An escalation is no longer reported as a failed run.** `TEAMMATE.md` tells a
  blocked teammate to say so, file a note, and stop — and `spawn.py` then refused
  that exact handback ("the teammate made no commits of its own"), stranding the
  worktree for the lead to salvage by hand. Reported from the field at real cost:
  four runs, three with zero commits, two of them correct escalations, one
  carrying a plan three review rounds deep. A record filed during the run now
  turns that refusal into a reported escalation naming the records to read, the
  work left behind, and exit 3. A teammate that simply did not finish, and said
  nothing, is refused exactly as before.
- **Python older than 3.11 now refuses by name instead of tracebacking.** Twelve
  of the thirteen shipped scripts died on 3.9 with `unsupported operand type(s)
  for |` — and `python3` on a stock Mac *is* 3.9. The README asked for 3.11+ and
  nothing enforced it, so a consuming project met a TypeError that named nothing:
  `setup.py` could not scaffold, and the SessionStart hook failed before its own
  "never break a session" guard could catch it. Now it says which interpreter it
  found and what it needs.
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
