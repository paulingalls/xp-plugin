---
name: xp-setup
description: >-
  Scaffold a repo for the xp process: .xp/ artifacts (seeded constraints,
  config, system + plan skeletons) and the git-hook wall. Never overwrites.
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
     own tooling (Playwright, pytest+subprocess, supertest, …) — judgment work,
     not scaffolding
   - a linter in the pre-commit hook
3. Plan the first milestone in `.xp/plan.md` — the skeleton card shows the
   format; every story needs runnable `Verify:` commands.
