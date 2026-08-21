# System Context — xp-plugin

**Product**: a lightweight XP process plugin for coding agents, targeting Claude Code
and Codex. Successor to xp-agents (see docs/AUDIT.md, docs/DESIGN.md). The product is
mostly prose (skills, agent charters, guides) plus a small Python core.

**Stack**: Python 3.11+, stdlib only — zero external packages, the predecessor's
strongest property. Markdown for all prose. lefthook for git hooks (dev of this repo);
pytest-xdist (-n auto) as a DEV-ONLY dep — the stdlib-only rule governs shipped code;
the plugin *scaffolds* equivalent hooks into consuming projects.

**Layout (target)**:
- `plugins/xp-plugin/` — the shipped plugin: .claude-plugin/plugin.json, skills/, agents/, hooks/ (per-harness), scripts/; root .claude-plugin/marketplace.json makes the repo a git marketplace
- `.xp/` — this repo's own instance of the state the plugin manages (we dogfood)
- `docs/` — audit, design
- shipped prose (VALUES.md, PROCESS.md) lives in plugins/xp-plugin/; .claude/ symlinks to it for dogfooding

**Surfaces & acceptance**: CLI (the scripts). Acceptance harness = the pytest suites
driving them as subprocesses (tests/test_*.py) — exit codes, stdout, filesystem effects.
Story ACs must be executed by a test named in the story's Verify.

**Conventions**:
- Test tiers: `fast` (pre-commit) / `story` (pre-push, story close) / `full`
  (sprint close). Declared in .xp/config.yml.
- Size budgets are acceptance criteria (DESIGN.md §9, rationale and numbers); run
  `plugins/xp-plugin/scripts/ratchet.py` for the live table — pre-push runs it too.
- **Worktree bootstrap**: none needed (stdlib only, no install step).
