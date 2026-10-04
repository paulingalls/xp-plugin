# xp-plugin

_Extreme Programming for coding agents, Claude Code and Codex._

xp-plugin gives a coding agent an XP process with a light touch. A card describes the
outcome, an agent implements it in its own worktree, and Git holds the work. Fresh-context
agents review the plan before code and the diff after it. The project's own git hooks run
its tests, and the plugin runs only a card's Acceptance command and the release suite.
Everything else is the agent's judgment, guided by [VALUES](plugins/xp-plugin/VALUES.md),
[JUDGMENT](plugins/xp-plugin/JUDGMENT.md) and the project's constraints.

## Install

Requires Python 3.11+, git, [gitleaks](https://github.com/gitleaks/gitleaks), and `gh`
for release PRs. [lefthook](https://github.com/evilmartians/lefthook) is optional; without
it, setup writes plain `.githooks/`. Install the plugin for every harness named in `roles`.

```bash
# Claude Code
claude plugin marketplace add paulingalls/xp-plugin
claude plugin install xp-plugin@xp-plugin --scope user

# Codex
codex plugin marketplace add paulingalls/xp-plugin
codex plugin add xp-plugin@xp-plugin
```

## Set up a repository

Run `/xp-setup`, or `xp.py setup` directly. The session banner prints the absolute path
to `xp.py`. Setup writes `.xp/config.yml`, `.xp/constraints.md`, `.xp/system.md`, the git
hooks and an empty plan, and refuses if `.xp/` already exists. Then fill in:

- **Every `EDIT-ME` in the hooks.** pre-commit runs lint and quick tests in under a minute.
  pre-push runs the broader tests. The `sprint` hook is the release suite. `nightly` is
  optional and wired to your own scheduler. Test commands live only here.
- **`.xp/config.yml`.** Set `version_files` and `roles` (below).
- **`.xp/system.md`.** Describe the product, especially Surfaces & acceptance.
- **`.xp/constraints.md`.** Keep the project's rules, at most ten, which reviewers cite.

## The cycle

Every scope runs plan, review the plan, do, review the diff, land.

| Scope | Plan | Do | Diff reviewed | Lands on |
|---|---|---|---|---|
| story | one card | executor in a worktree | story branch since fork | sprint branch |
| sprint | the slate | its stories | sprint branch since trunk | trunk, tagged |
| free | one card | executor in a worktree | branch since trunk | trunk, patch tag |

The lead judges every finding: fix it, drop it with a reason, or file debt. The skills
`/create-sprint`, `/story-close`, `/sprint-close` and `/free-close` guide each step.

## Commands

```
xp.py setup                     scaffold .xp/ and the hooks
xp.py recover                   session digest, unfinished cards, open records
xp.py sprint plan <id>          fresh review of the slate
xp.py sprint open <id>          on branch sprint-<id>, cut from trunk
xp.py sprint review <id>        one reviewer per angle over the sprint, one fix pass
xp.py sprint land <id>          version check, trial merge, sprint hook, PR
xp.py sprint post-merge <id>    on trunk after the PR merges: tag and record
xp.py story <id>                plan, plan review, execute, review; only missing stages
xp.py story review <id>         one more diff review
xp.py story land <id>           trial merge, Acceptance on the merged tree, merge
xp.py free <slug>               a story cut from trunk
xp.py free land <slug>          PR against trunk
xp.py free post-merge <slug>    patch tag
xp.py bug | debt | note | resolve    records with a falsifier command
```

Every subcommand answers `--help`, and every refusal names the next action.

## The card

Cards live in the plan file that `recover` names.

```
#### story-001 — <title>   [planned]
Context: <one paragraph: what this story changes, for whom, and why now>
AC:
- Given a cart with no items, When the shopper adds one item, Then the cart shows 1 item
Files: src/cart.py, features/cart.feature
Acceptance: <your runner> features/cart.feature
Executor: codex/<model>/medium        (optional)
```

Status is `planned`, `in-progress`, `done` or `retired`; free cards use the id `free-<slug>`.
Acceptance is one command, run from the repo root, that executes the ACs; Gherkin is recommended.

## Configuration

| Key | Meaning |
|---|---|
| `trunk` | Release branch, only when it is not the default branch |
| `version_files` | Comma-separated JSON manifests whose version the tag must match, or `none` |
| `sprint_cap` | Advised stories per sprint |
| `debt_budget` | Maximum share of a sprint spent on debt |
| `codex_sandbox` | Sandbox for Codex agents: `danger-full-access` (default) or `workspace-write` |
| `roles` | `lead`, `planner`, `executor`, `reviewer`, each `harness/model[/effort]`; pick a reviewer from a different model family than the executor |

## Where state lives

The repository holds `.xp/` and the hooks. Everything else lives in a per-clone data root,
`~/.xp/data/<id>/` or `$XP_DATA`: the plan, records, session digest, story plans, reviews
and handbacks, release records, agent logs and worktrees. Clones never share a plan.

## Codex notes

- **Trust the hooks first.** Codex skips unapproved plugin hooks silently. Approve them
  with `/hooks`, and again after every plugin update.
- **A Codex lead needs `codex --sandbox danger-full-access`.** Under the default
  `workspace-write`, a nested `codex exec` cannot initialise inside another Codex session.
  The network a nested `claude -p` needs is also off. A Claude lead has no such limit.
- **Spawned Codex agents run with `danger-full-access` by default.** Setting
  `codex_sandbox: workspace-write` confines them, and also blocks nested `codex exec`,
  Docker and loopback networking inside them.
