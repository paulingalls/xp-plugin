# System Context — xp-plugin

**Product**: a lightweight XP process plugin for coding agents, targeting Claude Code
and Codex. Successor to xp-agents (see docs/AUDIT.md, docs/DESIGN.md). The product is
mostly prose (skills, agent charters, guides) plus a small Python core.

**Stack**: Python 3.11+, stdlib only — zero external packages, the predecessor's
strongest property. Markdown for all prose. lefthook for git hooks (dev of this repo);
the plugin *scaffolds* equivalent hooks into consuming projects.

**Layout (target)**:
- `plugins/xp-plugin/` — the shipped plugin: .claude-plugin/plugin.json, skills/, agents/, hooks/ (per-harness), scripts/; root .claude-plugin/marketplace.json makes the repo a git marketplace
- `.xp/` — this repo's own instance of the state the plugin manages (we dogfood)
- `docs/` — audit, design
- shipped prose (VALUES.md, PROCESS.md) lives in plugins/xp-plugin/; .claude/ symlinks to it for dogfooding

**Conventions**:
- Test tiers: `fast` (pre-commit) / `story` (pre-push, story close) / `full`
  (sprint close). Declared in .xp/config.yml.
- Size budgets are acceptance criteria (DESIGN.md §9): Python ≤5,000 lines
  (spawn ≤2,000 · close ≤800 · hooks+adapters ≤1,000 · misc ≤1,200), skill prose
  ≤3,000 words, agent prose ≤2,500 words, tests ≤2× code lines.
- Worktree bootstrap: none needed (stdlib only, no install step).
