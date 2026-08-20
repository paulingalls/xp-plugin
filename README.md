# xp-plugin

**Extreme Programming for coding agents — the lightweight successor to
[xp-agents](https://github.com/paulingalls/xp-agents).** Targets Claude Code and
Codex from one shared core. Status: **Sprint 0** — the process artifacts exist and
the plugin is being built under its own process.

## Why a successor

xp-agents works — its consuming projects carry ~10,000 green tests and commit
histories with real epistemics — but it grew to ~52k lines of hook code, ~35k words
of prose, and 34 hook bindings: a process tool violating its own simplicity value.
The [audit](docs/AUDIT.md) measured what actually earned its keep; the
[design](docs/DESIGN.md) keeps that 10% and deletes the rest.

## The razor

> Keep every mechanism that creates **independent adversarial pressure** on the work,
> and every cheap structural check that keeps durable artifacts consistent with each
> other. Delete every mechanism that creates **bookkeeping about** the work. Prefer
> one script over fifteen prose steps, one file over one taxonomy, a falsifier over
> a tracker.

## What that means concretely

- **Fresh-context adversarial review** at plan, story close, and sprint close — the
  single highest-value mechanism, measured. Reviewers fault-inject every guard.
- **Git hooks as the unforgeable floor** (secrets, lint, tests) — humans and both
  harnesses hit the same wall. CLI hooks are advisory lane-keeping: 4 bindings, not 34.
- **Declarative records, no bureaucracy**: a bug is a claim + a falsifier that reds
  now; a debt's falsifier is green and gets scheduled-or-dropped at sprint planning;
  telemetry is never filed.
- **Planning that agents can execute**: milestones with executable "done", stories
  with Given/When/Then ACs and runnable Verify commands.
- **Delegation-first economics**: an expensive model orchestrates; cheaper/different
  models execute and review (cross-harness where available).
- **Falsifiable size budgets**, CI-enforced: ≤5k lines of Python, ≤3k words of skill
  prose, tests ≤2× code. Every added rule must displace one.

## Layout

| Path | What |
|---|---|
| `docs/AUDIT.md` | Evidence: what xp-agents' mechanisms actually delivered |
| `docs/DESIGN.md` | The successor's architecture and build order |
| `plugins/xp-plugin/` | The shipped plugin: manifest, VALUES/PROCESS, agents, skills |
| `.xp/` | This repo's own instance of the state the plugin manages |
| `.claude/` | Symlinks into the plugin for dogfooding |

*by Paul Ingalls, with Claude — built under review by the process it implements.*
