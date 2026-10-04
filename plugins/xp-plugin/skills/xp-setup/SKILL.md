---
name: xp-setup
description: Scaffold a repo's .xp/ artifacts and its git hooks.
---

# xp-setup

Run setup once from inside the repository. It writes `.xp/config.yml`,
`.xp/constraints.md`, `.xp/system.md`, the hooks, and the plan in the data root,
and refuses if `.xp/` exists. Then fill in with the human what the scaffold
cannot know: every `EDIT-ME` in the hook files (quick tests at pre-commit, under
a minute; broader tests at pre-push; the release suite in the `sprint` hook;
`nightly` if the project wants one); `versioning` (and `version_files` when on) and `roles` in the config,
with a reviewer from a different model family than the executor; `.xp/system.md`,
especially Surfaces & acceptance; and `.xp/constraints.md`. Every harness the
roles name needs its binary on PATH; only the lead's harness needs the plugin. Then `/create-sprint`.

```
python3 <plugin root>/scripts/xp.py setup
```

The session banner prints the plugin root.
