# System Context — xp-plugin

**Product**: a lightweight XP process plugin for coding agents, targeting Claude Code
and Codex. Successor to xp-agents (see docs/AUDIT.md, docs/DESIGN.md). The product is
mostly prose (skills, agent charters, guides) plus a small Python core.

**Stack**: Python 3.11+, stdlib only — zero external packages, the predecessor's
strongest property. Markdown for all prose. lefthook for git hooks (dev of this repo);
pytest-xdist (-n auto) as a DEV-ONLY dep — the stdlib-only rule governs shipped code;
the plugin *scaffolds* equivalent hooks into consuming projects.

**Layout (target)**:
- `plugins/xp-plugin/` — the shipped plugin: .claude-plugin/plugin.json, skills/, agents/, hooks/ (one file, both harnesses), scripts/; root .claude-plugin/marketplace.json makes the repo a git marketplace
- `.xp/` — this repo's own instance of the state the plugin manages (we dogfood)
- `docs/` — audit, design
- shipped prose (VALUES.md, JUDGMENT.md, PROCESS.md, TEAMMATE.md) lives in plugins/xp-plugin/ and is injected from there; .claude/ symlinks the skills and agent charters for dogfooding

**Surfaces & acceptance**: CLI (the scripts). Acceptance harness = the pytest suites
driving them as subprocesses (tests/test_*.py) — exit codes, stdout, filesystem effects.
Story ACs must be executed by a test named in the story's Verify.

**Conventions**:
- Component and density totals are review guidance; structural file and
  measurement guards still refuse.
- **Worktree bootstrap**: none needed (stdlib only, no install step).
- **Concurrency**: at most two review streams and one `pytest -n auto` gate. Reviews
  have no wall-clock limit; rejoin instead of relaunching.
- **Triage**: name any tier that still covers a dropped debt; without coverage, the
  drop is final.
- **Lanes**: `docs/DESIGN.md` is shared by every card and never separates lanes; use
  the other files instead (measured twice in Sprint 9).
