# xp-plugin

**Extreme Programming for coding agents** — Claude Code + Codex. The lightweight
successor to [xp-agents](https://github.com/paulingalls/xp-agents). Status:
**Sprint 0** — the process artifacts exist; the plugin is being built under its own
process.

## The values are the product

XP is defined by five values — **Communication, Simplicity, Feedback, Courage,
Honesty** ([VALUES.md](plugins/xp-plugin/VALUES.md)). Every practice associated
with XP — TDD, pair programming, shared ownership, small releases, consistent
style — is *derived* from them. When a practice and a value conflict, the value
wins.

The predecessor lost sight of this. It grew to ~52k lines of hook code and ~35k
words of prose — a Simplicity failure — and accumulated mechanisms it could not
say no to or drop — a Courage failure ([audit](docs/AUDIT.md)). Injecting values
first isn't enough; nothing required their use, so nothing answered to them.

Here the values are **operational**, not decorative:

- They are the first thing injected into every agent — lead, teammate, reviewer.
- **Every mechanism must name the value it derives from** (table below); one that
  can't is cut.
- **Every review finding cites the value it defends.**
- **Every recorded decision names its value tradeoff** — which value won, which
  lost, why.
- Dropping things is a first-class operation: unscheduled debts drop, sacrificial
  features are pre-named, every added rule displaces one. Courage, exercised.

## The razor (Simplicity + Courage, applied to the plugin itself)

> Keep every mechanism that creates **independent adversarial pressure** on the work,
> and every cheap structural check that keeps durable artifacts consistent with each
> other. Delete every mechanism that creates **bookkeeping about** the work. Prefer
> one script over fifteen prose steps, one file over one taxonomy, a falsifier over
> a tracker.

## Mechanisms, and the values they derive from

| Mechanism | Derives from |
|---|---|
| Fresh-context adversarial review at plan, story close, sprint close; reviewers fault-inject every guard | Feedback, Honesty |
| Git hooks as the unforgeable floor (secrets, lint, tiered tests) — humans and both harnesses hit the same wall; CLI hooks advisory, 4 bindings not 34 | Feedback, Simplicity |
| Declarative records: a bug is a claim + falsifier that reds now; a debt's falsifier is green, scheduled-or-dropped at planning; telemetry never filed | Honesty, Simplicity |
| Milestones with executable "done", stories with Given/When/Then ACs and runnable Verify commands | Communication, Feedback |
| Delegation-first: expensive model orchestrates, cheaper/different models execute and review (cross-harness) | Feedback (independent perspectives) |
| CI-enforced size budgets: ≤5k lines Python, ≤3k words skill prose, tests ≤2× code; every rule displaces one | Simplicity, Courage |

## Layout

| Path | What |
|---|---|
| `docs/AUDIT.md` | Evidence: what xp-agents' mechanisms actually delivered |
| `docs/DESIGN.md` | The successor's architecture and build order |
| `plugins/xp-plugin/` | The shipped plugin: manifest, VALUES/PROCESS, agents, skills |
| `.xp/` | This repo's own instance of the state the plugin manages |
| `.claude/` | Symlinks into the plugin for dogfooding |

*by Paul Ingalls, with Claude — built under review by the process it implements.*
