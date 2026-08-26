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

(The local-checkout form — `codex plugin marketplace add /path/to/xp-plugin` —
is the one measured by this repo's own walks; the published form follows the
CLI's documented syntax.)

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

**What a Codex lead does not get.** None of these is a correctness gap — the
wall, the completion contract and the review-report contract are shared code:

- **The Stop gate is inert.** Codex's `PostToolUse` payload carries no
  success-or-failure field, so nothing writes the test status that gate reads and
  it never blocks. Your `Verify` guarantee is the one it always was: `close.py`
  runs it at close.
- **No turns/cost/duration line** when a spawned run ends. The exit code is the
  whole in-band verdict, which is why the spawn re-checks the *tree* rather than
  believing any harness's own report.
- **A spawned Codex teammate loads no hooks or skills at all** — `codex exec` has
  no `--plugin-dir`, so its whole profile is inlined into the prompt instead. The
  install above is for the lead; teammates need nothing.

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
3. **Plan a story** with your lead agent: a card with context, files,
   Given/When/Then acceptance criteria, and a runnable `Verify:` line. Multi-file
   changes get a plan review from a fresh-context reviewer before code.
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
shipped plugin itself lives under a test-enforced size budget (~5.5k lines of
Python, prose caps included): every added rule displaces one, and the total has
moved once in fifteen re-cuts — priced against measurement, never a reserve.

## Layout

| Path | What |
|---|---|
| `plugins/xp-plugin/` | The shipped plugin: manifest, VALUES/PROCESS, agents, skills, scripts, hooks |
| `docs/DESIGN.md` | Architecture, the measured dual-harness table, size budgets |
| `.xp/` | This repo's own instance of the state the plugin manages |
| `tests/` | The suite — production code, same 500-line file cap as the plugin |

## Inspired by xp-agents

xp-plugin is the successor to
[xp-agents](https://github.com/paulingalls/xp-agents), which proved the idea
and then taught the lesson: it grew to ~52k lines of hook code and ~35k words
of prose enforcing XP, until the machinery outweighed the values it served.
The [audit](docs/AUDIT.md) of what those mechanisms actually delivered picked
the survivors — fresh-context review, red-first TDD, executable acceptance,
fault injection — and this plugin rebuilds exactly those on a git-hook floor,
under a size budget its own release gate enforces. Same spirit, ~90% less
machinery, and this repo is built by the process it ships: every mechanism
here reviewed its own pull request.

*by Paul Ingalls, with Claude — built under review by the process it implements.*
