# CLAUDE.md

## What this is

xp-plugin: a light-touch XP process plugin for coding agents (Claude Code + Codex).
The shipped plugin is `plugins/xp-plugin/`; docs/PLAN-v1.md is the design authority
and docs/history/ holds what came before. We dogfood: this repo runs under the
plugin it ships. When in doubt, VALUES.md; conflicts resolve
Honesty > Courage > Simplicity > Feedback > Communication.

## Rules that are ours, not the plugin's

- **Shipped Python ≤ 4,000 lines; tests ≤ 2x shipped.** `python3 tests/scripts/ratchet.py`
  measures both and is the sprint hook's wall. Nothing under `plugins/xp-plugin/` may
  exist for this repo's benefit or name it, its caps, or any consuming project.
- **A field failure is answered first by deleting a mechanism.** A card that adds one
  states why deletion cannot fix it. The plugin's growth from 774 to 13,486 lines came
  from fixing each problem with a gate; the cut that reversed it is docs/PLAN-v1.md.
- **Fault-inject hard properties, once.** Advisory behavior gets no guard and no test.
- **Prose that instructs an agent to run something is a shipped path**: run it yourself
  before shipping the instruction.

## Commands

- Tests: `pytest -q -n 4` (the commit and push hooks run this). No test launches a real
  agent; the shipped paths are walked by hand before a release.
- Lint: `ruff check --fix . && ruff format .`
- Hooks: `lefthook install` once per clone. Never `--no-verify`.
- Running a plugin command on this repo: `python3 plugins/xp-plugin/scripts/xp.py --help`.
  Long legs: `run_in_background: true`, no timeout, output redirected to a file and read
  back. A pipe reports the pipe's exit status, not the leg's.

## Releases

Tag, manifest (`plugins/xp-plugin/.claude-plugin/plugin.json`) and CHANGELOG.md name one
version; `xp.py sprint land` refuses otherwise. Consumers install from the marketplace
cache, so a repo edit is not live until it is tagged and installed.
