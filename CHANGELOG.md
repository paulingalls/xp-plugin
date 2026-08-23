# Changelog

Release notes started at v0.6.0; earlier entries are summarized from their
tag and merge messages. Full detail lives in the merge history and the
per-sprint review reports.

## v0.6.1 — the wall stops reporting green having run nothing

- **The scaffolded wall refuses instead of warning.** `hook-lib.sh` had two
  paths that passed a commit having run nothing: a missing `gitleaks` warned
  and fell through, and an unset or still-`EDIT-ME` test tier returned 0. The
  second fired on a *freshly scaffolded* repo — setup seeds `EDIT-ME`, so the
  wall installed, the first commit passed, and no test had ever run. Both now
  exit 1 naming their next action. Reported from the field on a real monorepo.
- **`xp-setup` stops naming a hook it declined to write.** Where existing hook
  routing is found, the closing advice no longer says "add your linter to the
  pre-commit hook"; it names the actual task — point `.xp/config.yml`'s tiers
  at the existing wall's own commands, so the two cannot drift into different
  definitions of "fast".
- **The release identity is now enforced, not just mandated.** v0.6.0 was
  tagged with the manifest still at 0.5.0; since the manifest version keys the
  consumer's plugin cache, that tag shipped the previous copy under a new name.
  `tests/test_release.py` refuses a manifest behind the latest tag, or a
  version with no CHANGELOG entry (constraint 14).

## v0.6.0 — either harness, any role (Sprint 5)

- **Headless plan review** (`plan_review.py`): the last subagent riding a
  harness tool became a config role — `harness/model/effort` like every other
  agent, launched through the shared runner. A codex teammate can now run its
  mandatory plan review (via a claude reviewer — see below).
- **Per-story `Reviewer:` card lines**, alongside `Executor:` — one card can
  say "author codex, review claude" and the next the inverse.
- **Every spawned agent streams**: one runner (`run_stream`) for teammates,
  reviewers, and plan reviewers — live tailable logs per role under the data
  root, native harness transcript pointers recorded, wall clocks preserved.
  Authored by codex (`gpt-5.6-sol`), reviewed by claude — the project's
  original pairing, now the default configuration.
- **The environment file** (`env.json` in the data root): setup seeds it,
  SessionStart refreshes it on both harnesses; processes nothing spawned
  (codex-lead scripts, hooks) resolve the installed plugin root through a
  validating reader that refuses stale or skewed installs loudly.
- **Codex sandbox facts, measured and shipped**: commits from linked
  worktrees need the git-common-dir widening (applied automatically,
  cwd-keyed); the executor leg gets sandbox network access (nested reviews
  need the API); codex cannot nest codex on macOS (upstream app-server
  limitation) — nested spawns route cross-harness by config.
- **`Files:` is a starting map, not a permission list**: implementations
  extend it and report deviations; an undeclared `.xp/` path remains a hard
  stop. (Measured cost of the old rule: ~500k tokens of plan-gate restarts.)
- Fast tier re-pinned at 55s for a doubled suite; 11 deep land-leg
  integration tests moved to the pre-push tier.

## v0.5.1 — free-mode patch release

- Duplicate story ids refuse instead of splitting across readers (the
  scaffold skeleton no longer collides with the natural first id). The first
  release shipped through `close.py free` — the card-less path to main.

## v0.5.0 — usable elsewhere, parallel here (Sprint 4)

- Per-clone execution plans; overlap-based land guards (trial merge, tier on
  the merged tree, ancestor and authorship checks); `[ready]` as a minted
  credential; one release review with angles (find → judge → fix → clear,
  security among the angles); codex as spawnable executor and reviewer with
  measured env-policy pins; codex as native lead (one hooks file, honest
  degradations); free mode.

## v0.4.0 and earlier

- The self-hosting core: story/sprint close pipelines, fixing reviewers,
  the git-hook wall, declarative records with falsifiers, the size ratchet.
