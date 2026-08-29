---
name: xp-setup
description: >-
  Scaffold a repo for the xp process: .xp/ artifacts (constraints, config,
  system) and the git-hook wall. The plan is NOT in the repo — it is per
  clone, in the state root. Never overwrites.
---

# xp-setup

1. Run `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/setup.py` from anywhere in the
   repo. It refuses if `.xp/` exists; pre-existing hook
   routing (incl. live `.git/hooks`) makes it SKIP the wall half — read its
   output rather than assuming.
2. With the human, fill in what the scaffold cannot know:
   - `tests.fast/story/full` in `.xp/config.yml` — the wall reads these at run
     time, so this is the only place tiers live
   - `.xp/system.md`, especially **Surfaces & acceptance**: every surface the
     product presents (HTTP / Browser / CLI / SDK / Automation / Message-event)
     needs a harness that drives it at its boundary; a surface without one is
     the first debt worth filing. Wire acceptance harnesses with the project's
     own tooling (browser, subprocess, request harnesses, …) — judgment work,
     not scaffolding
   - a linter in the pre-commit hook
3. Plan the first milestone in the plan the scaffold wrote — it is PER CLONE,
   outside the repo, and setup prints its path. The skeleton card shows the
   format; every story needs runnable `Verify:` commands.
