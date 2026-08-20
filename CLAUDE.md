# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

xp-plugin: a lightweight XP process plugin for coding agents (Claude Code + Codex),
the successor to ../xp-agents. We **dogfood the process while building it** — this
repo runs under the same artifacts the plugin will ship. docs/AUDIT.md (evidence)
and docs/DESIGN.md (architecture, decided) are the authorities; don't re-litigate
settled decisions, propose diffs to them instead.

## The process, enforced

- Multi-file change → draft plan → spawn `plan-reviewer` agent → address findings →
  then write code. Red test first; never fake a red for config/docs commits — say so
  in the commit body.
- Story done → run the `/story-close` checklist (spawns `story-reviewer`).
- Records (bug/debt/note) per PROCESS.md; mid-sprint you may record, never schedule.
- Git hooks (lefthook) are the wall: ruff + gitleaks + fast tests at commit, full
  suite at push. Don't bypass them (`--no-verify` is a values violation, not a trick).

## Commands

- Test fast tier: `pytest -q -m "not slow"` · full: `pytest -q`
- Lint: `ruff check --fix . && ruff format .`
- Hooks: `lefthook install` (once per clone)

## Size discipline (CI-enforced once the ratchet lands)

Python ≤5,000 lines (spawn ≤2,000 · close ≤800 · hooks+adapters ≤1,000 · misc
≤1,200) · skill prose ≤3,000 words · agent prose ≤2,500 words · tests ≤2× code
lines. Every added rule displaces one. When in doubt: VALUES.md, conflicts resolve
Honesty > Courage > Simplicity > Feedback > Communication.
