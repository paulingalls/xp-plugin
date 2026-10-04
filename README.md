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
it, setup writes plain `.githooks/`. Install the plugin for the harness you lead from; a
harness that only runs agents needs its binary on PATH.

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
- **`.xp/config.yml`.** Set `versioning`, `version_files` if it is on, and `roles` (below).
- **`.xp/system.md`.** Describe the product, especially Surfaces & acceptance.
- **`.xp/constraints.md`.** Keep the project's rules, which reviewers cite. Cap the entire
  UTF-8 file at 4,500 bytes to fit Codex's 10,000-byte SessionStart hook limit.

## Upgrading from 0.x

1. Finish in-flight work on 0.36.x before installing v1; no state migrates. Edit the
   existing `.xp/` in place: setup is for fresh repositories and refuses an existing one.
2. Update each installed harness:

   ```bash
   # Claude Code
   claude plugin marketplace update xp-plugin
   claude plugin update xp-plugin@xp-plugin

   # Codex
   codex plugin marketplace upgrade xp-plugin
   codex plugin add xp-plugin@xp-plugin
   ```

   Restart to load the update. In Codex, re-approve plugin hooks with `/hooks`.
3. Edit `.xp/config.yml` against [Configuration](#configuration) and the
   [config template](plugins/xp-plugin/templates/config.yml). Explicitly choose
   `versioning: on` or `off`; with `on`, set `version_files`, and add a `CHANGELOG.md`
   whose first `## ` heading names the current version if the project has none. Remove `tests`, `sprint_cap`,
   `release`, `preflight`, `constraints_chars_cap`, `profile_target`,
   `teardown_timeout` and `review`: unused keys are silently ignored. Remove the `finder`,
   `verifier` and `closer` seats; `angle-reviewer` replaces the sprint review seats and
   falls back to `reviewer`. Keep the required seats; Configuration lists the optional ones.
   Keep `lifecycle_command` as a shell line (v0.36 ran an argv). Move `.xp/system.md`'s
   Worktree bootstrap and teardown commands into `worktree_setup` and `worktree_teardown`;
   remove those labelled lines from system.md.
4. Move test commands into the project's existing hooks: quick checks at pre-commit,
   broader checks at pre-push, the release suite at `sprint`, optional expensive checks at
   nightly. Move the old `preflight` command to the start of the `sprint` hook. Add lefthook `sprint:` or an executable `.githooks/sprint`, according to the
   existing routing. Adapt the [lefthook template](plugins/xp-plugin/templates/lefthook.yml)
   or [plain sprint hook](plugins/xp-plugin/templates/githooks-sprint); preserve existing hooks.
   Delete hook steps that read a removed key (`tests`, `constraints_chars_cap`) or call a
   0.x plugin script: with the key gone they refuse every commit.
   If the hooks scan no secrets, adopt the template's gitleaks jobs (pre-commit,
   pre-merge-commit, pre-push); setup adds them only to new repositories.
5. Convert open cards from `Verify:` to `Acceptance:`; retire cards about removed 0.x
   machinery. Preserve applicable acceptance obligations. Re-file each open 0.x bug or debt
   with `xp.py bug` / `xp.py debt` (falsifier included), or drop it with a reason: v1 reads
   only its own record headings, so 0.x records remain in `<data>/work.md` as history and
   never appear as open in `xp.py recover`.
6. Apply the [constraints template](plugins/xp-plugin/templates/constraints.md) items to
   the project's constraints.
7. Rewrite the project's own agent instructions (CLAUDE.md, AGENTS.md, process notes) that
   name 0.x commands such as `spawn.py`, `close.py` or `Verify:`. Agents read them every
   session, and they outrank what they remember of the plugin.

## The cycle

Every scope runs plan, review the plan, do, review the diff, land.

| Scope | Plan | Do | Diff reviewed | Lands on |
|---|---|---|---|---|
| story | one card | executor in a worktree | story branch since fork | sprint branch |
| sprint | the slate | its stories | sprint branch since trunk | trunk, tagged |
| free | one card | executor in a worktree | branch since trunk | trunk, patch tag |

The lead judges every finding: fix it, drop it with a reason, or file debt. The skills
`/create-sprint`, `/story-close`, `/sprint-close` and `/free-close` guide each step.

Merge a PR any way your host allows. Merge commits are preferred, because post-merge then
finds the branch in trunk's history; squash and rebase merges work, and post-merge says so.

## Commands

```
xp.py setup                     scaffold .xp/ and the hooks
xp.py recover                   session digest, unfinished cards, open records
xp.py sprint plan <id>          fresh review of the slate
xp.py sprint open <id>          on branch sprint-NNN (sprint 7 is sprint-007), cut from trunk by you
xp.py sprint review <id>        one reviewer per angle over the sprint, one fix pass
xp.py sprint land <id>          version check, trial merge, sprint hook, PR
xp.py sprint post-merge <id>    on trunk after the PR merges: record, and tag under versioning: on
xp.py story <id>                plan, plan review, execute, review; only missing stages
xp.py story review <id>         one more diff review
xp.py story land <id>           trial merge, Acceptance on the merged tree, merge
xp.py free <slug>               mint the card; run again to walk it as a story cut from trunk
xp.py free land <slug>          PR against trunk
xp.py free post-merge <slug>    close the patch; tag it under versioning: on
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
Executor: codex/<model>/medium
```

The Executor line is optional and overrides `roles.executor`.

Status is `planned`, `in-progress`, `done` or `retired`; free cards use the id `free-<slug>`.
Acceptance is one shell line, run from the repo root, that executes the ACs; Gherkin is
recommended. Falsifiers are shell lines too, run once when a record is filed or resolved.

## Configuration

| Key | Meaning |
|---|---|
| `trunk` | Release branch, only when it is not the default branch |
| `versioning` | Required: `off`: the project owns versions and tags; `on`: every sprint and free patch is tagged |
| `version_files` | With versioning on: comma-separated JSON manifests whose version the tag must match, or `none` |
| `worktree_setup` | Optional shell line in a new story/free worktree, before any agent. Nonzero refuses and removes the worktree and any branch created by that attempt. Agents start only after it passes; a run killed mid-setup reruns it in the same worktree, so it must tolerate a rerun |
| `worktree_teardown` | Optional shell line inside the worktree before `story land` or `free post-merge` removes it. Nonzero warns and cleanup continues: the merge has landed. `free land` keeps the worktree |
| `lifecycle_command` | Optional shell line with two appended, shell-quoted arguments: event and id. `sprint-open <id>` runs in the invoking repo root before recording the open sprint; `story-close <card-id>` in the story worktree after green Acceptance and before merge; `sprint-close <id>` in the invoking repo root during post-merge before the tag/release record. Nonzero refuses the guarded step. Free patches emit no lifecycle events |
| `debt_budget` | Maximum share of a sprint spent on debt |
| `codex_sandbox` | Sandbox for Codex agents: `danger-full-access` (default) or `workspace-write` |
| `roles` | Seats, each `harness/model[/effort]`. Required: `lead`, `planner`, `executor`, `reviewer`; pick a reviewer from a different model family than the executor. Optional, falling back to their family when unset: `plan-reviewer` (one card's plan; falls back to `reviewer`), `slate-reviewer` (the slate; falls back to `plan-reviewer`), `angle-reviewer` (sprint review; falls back to `reviewer`), `fixer` (the sprint fix pass; falls back to `executor`). Each is its own charter under `agents/` |

Project commands run with `sh -c`; unset or empty keys disable them. Configuration comes
from the invoking checkout. Output streams live and logs stay under `<data>/logs/`.
Projects bound their own scripts and make them tolerate retries: failed lifecycle steps
and teardown cleanup may rerun. A sprint-close retry after its release tag skips the event.
Setup runs only when the worktree is created; dry-runs and free-card minting run no commands.

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
