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

- Multi-file change → draft plan → `scripts/plan_review.py <story-id> <plan-file>` →
  re-read the plan, the reviewer's edits land there → then write code. Red test
  first; never fake a red for config/docs commits — say so in the commit body.
- Story done → run the `/story-close` checklist (spawns `story-reviewer`).
- Records (bug/debt/note) per PROCESS.md; mid-sprint you may record, never schedule.
- Git hooks (lefthook) are the wall: ruff + gitleaks + fast tests at commit, full
  suite at push. Don't bypass them (`--no-verify` is a values violation, not a trick).

## Commands

- Test tiers live in `.xp/config.yml` — run those spellings, they carry `-n auto`
  (serial pytest is ~6x slower): fast `pytest -q -n auto -m "not slow"` · full `pytest -q -n auto`
- Lint: `ruff check --fix . && ruff format .`
- Hooks: `lefthook install` (once per clone)

## Size discipline

Budgets and rationale live in DESIGN.md §9; `tests/scripts/ratchet.py` measures the
Python ones live at pre-push (the prose budgets are still read-and-judge) — run it
and read the table, never a cached number. It measures the SHIPPED plugin, so it
lives outside it: nothing under `plugins/xp-plugin/` may exist for our benefit
rather than a consuming project's. Every added rule displaces one. When in doubt:
VALUES.md, conflicts resolve Honesty > Courage > Simplicity > Feedback >
Communication.

## Authoring skills (ours, not a consuming project's)

A SKILL driving a script says what to run, what you own, and how to respond to
results. Mechanism lives in the code and remediation in the refusal text, so
describing either ships a second copy that only drifts. Negative space — what
deliberately does not exist — is the one description that earns its words.
This only works if the script speaks: every refusal names its next action, and
every CLI answers `--help` without doing anything.

## Mid-sprint cap moves (this repo's convention, learned at Sprint 4)

A rebalance edit (ratchet.py + DESIGN §9) lands on trunk BEFORE any review
round it must cover and AFTER any land in flight — the wall runs the tree's
own ratchet, so an in-flight branch blocked by old caps applies the identical
edit in its own tree (twin edits merge clean). Measured: notes 86575dfa,
story-023's second round.
