---
name: xp-setup
description: Scaffold a repo's .xp/ artifacts and the git-hook wall.
---

# xp-setup

The plan is NOT in the repo — it is per clone, in the state root.

1. Run `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/setup.py` from anywhere in the
   repo. It refuses if `.xp/` exists — never overwrites; pre-existing hook
   routing (incl. live `.git/hooks`) makes it SKIP the wall half — read its
   output rather than assuming.
2. With the human, fill in what the scaffold cannot know:
   - `.xp/constraints.md`, seeded from the plugin template
   - `tests.fast/story/full` in `.xp/config.yml` — the wall reads these at run
     time, so this is the only place tiers live
   - `.xp/system.md`, especially **Surfaces & acceptance**: every surface the
     product presents (HTTP / Browser / CLI / SDK / Automation / Message-event)
     needs a harness that drives it at its boundary; a surface without one is
     the first debt worth filing. Wire acceptance harnesses with the project's
     own tooling (browser, subprocess, request harnesses, …) — judgment work,
     not scaffolding
   - a linter in the pre-commit hook
3. Set `roles.executor` with the human — the scaffold ships a default, so reading
   it unasked offers the harness the template guessed, not the team's. That
   harness's teammates need a user install of this plugin; offer to run its pair:
   - Claude: `claude plugin marketplace add paulingalls/xp-plugin`, then
     `claude plugin install xp-plugin@xp-plugin --scope user`
   - Codex: `codex plugin marketplace add paulingalls/xp-plugin`, then
     `codex plugin add xp-plugin@xp-plugin`
   Only if they accept; declining or a failure never undoes setup — report and
   continue. If marketplace add says the name exists, the source is there: run
   the second command anyway, not `marketplace upgrade` — on codex that refreshes
   a Git source but exits 0 without touching a local one.
4. Run `/create-sprint` to plan the first milestone at the per-clone plan path
   setup prints.
