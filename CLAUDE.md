# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

xp-plugin: a lightweight XP process plugin for coding agents (Claude Code + Codex),
the successor to ../xp-agents. We **dogfood the process while building it** — this
repo runs under the same artifacts the plugin will ship. docs/AUDIT.md (evidence)
and docs/DESIGN.md (architecture, decided, including the size budget in §9) are
the authorities; don't re-litigate settled decisions, propose diffs to them
instead.

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

## Size discipline

Budgets and rationale live in DESIGN.md §9; `ratchet.py` enforces them live at
pre-push — read the table it prints, not a cached number. Every added rule
displaces one. When in doubt: VALUES.md, conflicts resolve Honesty > Courage >
Simplicity > Feedback > Communication.
