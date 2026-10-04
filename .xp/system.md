# System

**Product**: xp-plugin, a light-touch XP process plugin for coding agents on Claude
Code and Codex. One entry point (`xp.py`), seven agent charters, the project's own
git hooks for tests. This repo runs under the plugin it ships.

**Stack**: Python 3.11+, stdlib only in shipped code. Markdown for all prose. Dev
only: pytest with pytest-xdist (`pytest -q -n 4`), ruff, lefthook, gitleaks.

**Surfaces & acceptance**: CLI (`plugins/xp-plugin/scripts/xp.py` and its
subcommands) and the SessionStart hook. The harness is the pytest suite under
`tests/`, driving the CLI in scratch git repositories with `XP_DATA` set: exit
codes, stdout, and the files and refs left behind. Agent launches are not tested;
every shipped path is walked by hand in a scratch consumer before a release.

**Layout**:
- `plugins/xp-plugin/scripts/xp.py` — the dispatcher; `xpcore/` holds one module
  per concern (config, cards, gitx, launch, bundle, story, land, sprint, release,
  records, session, setup, hooks)
- `plugins/xp-plugin/agents/` — one charter per artifact: planner, plan-reviewer,
  slate-reviewer, executor, reviewer, angle-reviewer, fixer
- `plugins/xp-plugin/angles/` — one file per sprint-review angle
- `plugins/xp-plugin/skills/` — the five skills; `.claude/` symlinks them for dogfooding
- `plugins/xp-plugin/templates/` — what `xp.py setup` scaffolds into a consumer
- `plugins/xp-plugin/{VALUES,JUDGMENT,PROCESS}.md` — injected at session start
- `docs/PLAN-v1.md` — the design authority; `docs/history/` — what came before
- `tests/scripts/ratchet.py` — the size wall the sprint hook runs

**Worktree setup**: none (stdlib only, no install step).

**Conventions**:
- Nothing under `plugins/xp-plugin/` names this repo, its caps or any consumer.
- Prose that instructs an agent to run something is a shipped path: run it first.
- Plugin changes are not live until tagged and installed from the marketplace
  cache; run repo scripts by path to exercise the tree.
