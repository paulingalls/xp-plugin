```
██╗  ██╗██████╗       ██████╗ ██╗     ██╗   ██╗ ██████╗ ██╗███╗   ██╗
╚██╗██╔╝██╔══██╗      ██╔══██╗██║     ██║   ██║██╔════╝ ██║████╗  ██║
 ╚███╔╝ ██████╔╝══════██████╔╝██║     ██║   ██║██║  ███╗██║██╔██╗ ██║
 ██╔██╗ ██╔═══╝       ██╔═══╝ ██║     ██║   ██║██║   ██║██║██║╚██╗██║
██╔╝ ██╗██║           ██║     ███████╗╚██████╔╝╚██████╔╝██║██║ ╚████║
╚═╝  ╚═╝╚═╝           ╚═╝     ╚══════╝ ╚═════╝  ╚═════╝ ╚═╝╚═╝  ╚═══╝
```

# _Extreme Programming for coding agents_

xp-plugin runs your coding agents — Claude Code and Codex, solo or in
parallel — through a real XP loop: planned stories with executable acceptance
criteria, red tests first, fresh-context adversarial reviews that **fix** what
they find, and a release gate no agent can talk its way past. The values do
the steering; git hooks do the enforcing; agents do the work.

**What it does:** you plan stories together with your lead agent, then it
spawns teammates (either harness, any model, per story) into isolated
worktrees. Every story closes through an independent reviewer that commits
fixes under its own identity; every sprint releases through a multi-agent
find → judge → fix → clear pipeline; every merge to main is version-bumped.
Small out-of-sprint fixes get a legal path too (`free` mode), so nothing moves
main by hand.

**How it enforces:** deterministic rules live in git hooks — secrets scan,
lint, tiered tests at commit and push — which humans and both harnesses hit
identically. Judgment lives in headless reviewer agents with fresh context.
CLI hook markers are advisory lane-keeping, never security; the wall is git.

**Who it's for:** anyone running Claude Code or Codex on a codebase they
intend to keep. Solo use gets you the discipline (TDD ordering, reviews,
honest records). Team-of-agents use gets you parallel stories in worktrees
with per-clone plans — three clones of one repo run three independent plans.

---

## Install

From a Claude Code session:

```
/plugin marketplace add paulingalls/xp-plugin
/plugin install xp-plugin@xp-plugin
```

Or from your terminal:

```bash
claude plugin marketplace add paulingalls/xp-plugin
claude plugin install xp-plugin@xp-plugin --scope user
```

### On Codex

```bash
codex plugin marketplace add paulingalls/xp-plugin
codex plugin add xp-plugin@xp-plugin
```

**You must trust the hooks, or nothing fires.** Codex skips unreviewed
plugin hooks *silently*: run `/hooks` interactively and approve (per content
hash — repeat after every update), or pass `--dangerously-bypass-hook-trust`
headless. One `hooks.json` serves both harnesses; there is no codex-specific
hook file to maintain.

**Launching the lead.** The hooks and the session injection work in a plain
`codex` session once you have trusted them above. Spawning does not: every
story, review and plan review launches a nested harness from *inside* the lead's
own sandbox, and Codex's default `workspace-write` denies both halves of that —
a nested `codex exec` cannot initialise (`failed to initialize in-process
app-server client: Operation not permitted`) and the network a nested `claude
-p` needs is off (DNS refused, curl exit 6). Both measured on 0.149.0 against
`codex exec`; an interactive lead may prompt you to escalate instead, which we
have not walked. No flag on the *inner* run fixes either — the outer posture is
the whole difference, so launch the lead with:

```bash
codex --sandbox danger-full-access
```

A Claude lead has no such constraint. What the flag does *not* change is the
teammate's own posture: spawned legs are launched unconfined either way (below),
so a Codex teammate can nest its own plan review.

**What teammates are launched with.** Every Codex teammate and reviewer runs
`--sandbox danger-full-access`, and every launch prints the posture it took.
**That is the default, not the only choice**: `codex_sandbox: workspace-write`
in `.xp/config.yml` confines them, and the launch line names the cost — no
Docker socket, no loopback TCP, no nested `codex exec`, so a teammate's
mandatory plan review cannot reach an API. Unconfined by default is a decision,
not an oversight: a Claude teammate already runs with no OS sandbox because
Claude Code exposes none. What bounds both harnesses is the same either way: a
throwaway worktree, the git-hook wall, and `close.py` running your `Verify`.

**What a Codex lead does not get.** Sprint 8's live Codex-lead walk classifies
each claim; the wall, completion contract and review-report contract remain
shared code:

- **UNEXERCISED — the Stop gate's Codex path.** The walk left no test-status
  marker, which cannot distinguish a hook that ran and wrote nothing from one
  that never ran. The deterministic payload analysis still says Codex provides
  no success-or-failure field; `close.py` remains the `Verify` guarantee.
- **CONFIRMED — no turns/cost/duration line** when a spawned run ends. The exit
  code is the whole in-band verdict, which is why spawn re-checks the *tree*
  rather than believing either harness's report.
- **CORRECTED — spawned Codex teammates do load installed hooks and skills, once
  you have trusted them.** All five Sprint 8 teammate sessions received the
  installed SessionStart hook and skill catalog. The trust you granted above is
  what carries: Codex stores it per hook content hash in `~/.codex/config.toml`,
  not per session, and the spawn passes no `--dangerously-bypass-hook-trust` of
  its own — so without that approval, or after an update changes the hash, a
  spawned teammate's hooks are skipped as silently as a lead's. `codex exec` still
  has no `--plugin-dir`, so the worktree's authoritative teammate profile is
  inlined; an older user install can therefore disagree with the commands the
  prompt names.

**Requirements:** Python 3.11+, git. [lefthook](https://github.com/evilmartians/lefthook)
and [gitleaks](https://github.com/gitleaks/gitleaks) for the enforcement wall
(setup scaffolds the config if lefthook is installed). `gh` for release PRs.

## Get started

1. **Scaffold**: run `/xp-setup` in your repo. It writes `.xp/` (config,
   constraints seed, system notes), installs the git-hook wall, and creates
   your execution plan — **per clone, outside the repo** (it prints the path).
   It never overwrites anything that exists.
2. **Fill in what only you know**: your test commands in `.xp/config.yml`
   (`tests.fast/story/full` — the wall reads these at run time) and your
   product's surfaces in `.xp/system.md`.
3. **Plan a story**: give its context, files, Given/When/Then criteria and
   `Verify:` commands. They run as argv from the repo root, with no shell or `cd`;
   pass a needed working directory through the runner itself, for example
   `Verify: uv run --directory apps/biographer python -m unittest`. Multi-file
   changes get fresh-context plan review before code.
4. **Mint and spawn**: `spawn.py ready story-001` turns the reviewed card into
   a credential ([ready] is earned, not typed); `spawn.py story-001` launches
   the teammate in its own worktree — Claude or Codex, chosen per story with
   `Executor: <harness>/<model>/<effort>` on the card.
5. **Close**: `/story-close` runs the Verify commands and spawns a reviewer
   that reads the whole diff, commits fixes under its own identity, and files
   what it can't fix. Landing merges only what review covered — overlap with
   trunk, rewritten history, gate-file edits, and dirty trees all refuse with
   the remedy named.
6. **Release**: `/sprint-close` re-runs every filed falsifier, walks you
   through note triage and a retro, then gates the release on a multi-stage
   review — blind finders over the whole sprint diff, verifiers that refute,
   one fixer, one blockers-only closing pass — and opens the PR with the
   version bump. `close.py free <slug>` does the same honesty at patch scale
   for out-of-sprint fixes.

## Configure: `.xp/config.yml`

Read at run time — an edit takes effect on the next command. Nothing caches.

**Test tiers.** The wall's definition of green. Commands run under `sh -c`; the
git hooks re-read them each run, so retuning a tier never means editing a hook.
A tier left `EDIT-ME` or empty refuses when it would run — a gate that reports
green having run nothing is worse than no gate.

```yaml
tests:
  fast: pytest -q -m "not slow"   # pre-commit — seconds, not minutes
  story: pytest -q                # pre-push and story close
  full: pytest -q --runslow       # sprint close, e2e included
```

Optional, and only together: a record filed `--covered-by fast` is satisfied
when a covering tier runs, so sprint close doesn't re-run it. The pins are the
guard — retune a tier without updating its pin and the falsifier batch refuses
and names the drift.

```yaml
tier_coverage:        # covered: covering (transitive, so chains work)
  fast: story
  story: full
tier_coverage_pins:   # each named tier's command, exactly as it reads today
  fast: pytest -q -m "not slow"
  story: pytest -q
  full: pytest -q --runslow
```

**Roles.** `harness/model[/effort]`; harness is `claude` or `codex`. A card's
`Executor:` or `Reviewer:` line overrides config for that story.

| Role | Runs |
|---|---|
| `lead` | you, in your own session — declared for the record |
| `planner` → `executor` | the implementation plan for a multi-file story |
| `plan-reviewer` | adversarial read of that plan, before code |
| `executor` | the teammate that writes the story |
| `reviewer` | story close, over the cumulative diff |
| `slate-reviewer` → `reviewer` | the whole slate, at sprint open |
| `card-refresher` → `reviewer` | one card's stale claims, against HEAD |
| `finder` `verifier` `fixer` `closer` → `reviewer` | the four sprint-close review stages |

`→` is the fallback when the key is absent, so an older config keeps working. A
role with no key and no fallback refuses and prints the line to paste.

**Everything else.**

| Key | Values | Absent | What it does |
|---|---|---|---|
| `release` | `sprint`, or anything else | stories land on trunk | `sprint`: stories merge into the sprint branch this clone recorded at `close.py sprint <id> start`, and sprint close PRs it to trunk. Otherwise stories land on trunk directly. |
| `trunk` | branch name | git's default | Where releases land and tag. A configured branch that doesn't exist refuses — it never falls back. |
| `version_files` | manifest paths, comma-separated, or `none` | refuses at release | The tag must match `version` in every named manifest. `none` waives the wall and says so on the release line. |
| `sprint_cap` | integer | refuses at slate review | Story slots a sprint may spend. |
| `debt_budget` | fraction | refuses at slate review | Max share of those slots that may be scheduled debt. |
| `constraints_chars_cap` | integer | refuses at commit | Character ceiling on `.xp/constraints.md`, enforced by the commit hook. |
| `profile_target` | integer | `806` | Story-card token allowance. Over it, spawn names the largest contributor — a warning, not a refusal. |
| `codex_sandbox` | `danger-full-access`, `workspace-write` | `danger-full-access` | Posture for every Codex role; each launch prints the one it took. `read-only` is refused — every role must write its deliverable. |
| `teardown_timeout` | seconds | `60` | Caps the worktree teardown command from `.xp/system.md`. |
| `review.verify_batches` | integer | `2` | Sprint-close verifier *agents* per round — candidates are batched across them, never one agent each. |
| `lifecycle_command` | argv prefix | no events fire | Your command at process events; see below. |

## Lifecycle events

`lifecycle_command` is an argv prefix — **no shell**, so `cd` and shell
metacharacters are refused rather than passed to one. Fixed arguments are fine.
The plugin appends the event and its id:

```yaml
lifecycle_command: ./scripts/xp-lifecycle "fixed value"
```

| Event | Fires at | Second arg | Non-zero exit |
|---|---|---|---|
| `sprint-open` | `close.py sprint <id> start`, on the open that records the branch | sprint id | refuses the open |
| `story-close` | `close.py story <id> land`, after the gates, before refs move | story id | refuses the land |
| `sprint-close` | `close.py sprint <id> post-merge`, on trunk, before the tag | sprint id | refuses before tagging |

Free closes fire nothing, and a `--dry-run` of any leg fires nothing.

Separately, the plugin ships four **harness** hooks in one `hooks.json` for both
Claude and Codex: `SessionStart` injects values, process, constraints and the
recovery block; `PostToolUse` and `PostToolUseFailure` on Bash record whether a
story's `Verify` went green; `Stop` blocks once on a red `Verify` still in play.
All four are advisory lane-keeping. The wall is git.

## Where state lives

`.xp/` is small and hand-edited — three files, all yours:

| File | What |
|---|---|
| `config.yml` | the settings above |
| `constraints.md` | the rules reviewers cite; capped by `constraints_chars_cap` |
| `system.md` | product, stack, surfaces, layout, conventions, and the worktree bootstrap/teardown commands |

Everything the plugin *writes* lives outside the repo, in a data root keyed to
the clone (`~/.xp/data/<id>/`, or `$XP_DATA`) — so three clones of one repo run
three independent sprints, and none of it lands in your history:

| Path | What |
|---|---|
| `plan.md` | the roadmap: milestones, sprints, story cards |
| `work.md`, `archive.md` | the bug/debt/note ledger, and what's been retired from it |
| `session.md` | the short digest that carries the lead across sessions |
| `env.json`, `sprint_branch` | which plugin install manages this repo, and this clone's open sprint |
| `logs/`, `reports/`, `plans/` | teammate and reviewer transcripts, review reports, execution plans |
| `markers/`, `locks/`, `worktrees/`, `closes.jsonl` | close state, cross-lane locks, story checkouts, close telemetry |

## The commands

Skills you invoke: `/xp-setup`, `/create-sprint`, `/story-close`,
`/sprint-close`, `/free-close`. Under them the lead runs `spawn.py`,
`close.py`, `work.py` and `slate_review.py`; a teammate runs `plan_review.py`
on its own plan. Every one answers `--help` without doing anything, and every
refusal names the next action.

## What you get

- **The values, operational** — Communication, Simplicity, Feedback, Courage,
  Honesty ([VALUES.md](plugins/xp-plugin/VALUES.md)) injected into every agent;
  review findings cite the value they defend; conflicts resolve in a fixed
  order. Practices derive from values, and when they conflict, the value wins.
- **Both harnesses, really** — Codex teammates and reviewers carry the
  environment pins our gates need and hit the same git wall Claude ones do; the
  dual-harness ground rules are a table of *measured* facts in
  [DESIGN.md](docs/DESIGN.md), each stamped with the version it was verified
  against. What each harness is launched with, and what a Codex lead gives up,
  is under [On Codex](#on-codex).
- **Reviews that fix** — story reviewers commit repairs under their own git
  identity (authorship is the audit trail); the sprint pipeline kills
  plausible-but-wrong findings with independent verifiers before anything is
  fixed; every guard a review adds gets fault-injected to prove it can red.
- **Records with teeth** — a bug is a claim plus a falsifier that reds *now*;
  a debt's falsifier is green until the debt is paid; the whole ledger re-runs
  at every sprint close. No telemetry, no status fields, no event log.
- **Per-clone plans** — the execution plan lives in the state root keyed by
  clone, so parallel checkouts of one repo each run their own sprint without
  trampling each other.
- **Continuity** — teammate and reviewer sessions stream to project-scoped
  logs you can tail; a session digest carries the lead's context across
  sessions; costs and turn counts land in the record.

## What it refuses to have

Negative space is a feature. There is no event log, no status-message-market,
no per-commit review cadence, no conflict-detection telemetry, no force-close
matrix, and no hook empire — four CLI hook bindings, advisory by design. The
shipped plugin's component and prose-density measurements are reported at close
for reviewer judgment. Every added rule still displaces one, and the 500-line
structural file cap still binds shipped code and tests.

## Layout

| Path | What |
|---|---|
| `plugins/xp-plugin/` | The shipped plugin: manifest, VALUES/PROCESS, agents, skills, scripts, hooks |
| `docs/DESIGN.md` | Architecture, the measured dual-harness table, completed build record |
| `.xp/` | This repo's own config, constraints and system notes |
| `tests/` | The suite — production code, same 500-line file cap as the plugin |

## Inspired by xp-agents

xp-plugin is the successor to
[xp-agents](https://github.com/paulingalls/xp-agents), which proved the idea
and then taught the lesson: it grew to ~52k lines of hook code and ~35k words
of prose enforcing XP, until the machinery outweighed the values it served.
The [audit](docs/AUDIT.md) of what those mechanisms actually delivered picked
the survivors — fresh-context review, red-first TDD, executable acceptance,
fault injection — and this plugin rebuilds exactly those on a git-hook floor,
with its size visible to close review. Same spirit, ~90% less
machinery, and this repo is built by the process it ships: every mechanism
here reviewed its own pull request.

*by Paul Ingalls, with Claude — built under review by the process it implements.*
