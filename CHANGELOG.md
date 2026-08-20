# Changelog

## v0.2.1 — 2026-08-19 · post-release tweaks

Retro presentation becomes a close duty; changelog added; stale sprint_branch
key retired. Also the release-discipline fix these tweaks exposed: **main only
moves by release** — every merge to main bumps and tags, and between-sprint
work rides free branches (close.py card-less mode: Sprint-2).

## v0.2.0 — 2026-08-19 · Sprint 1: the self-hosting core

The plugin becomes real: installable, hook-driven, and built end-to-end under
the process it implements.

- **work.py** — bug/debt/note records with structural shapes: a bug's falsifier
  must red at filing, a debt's must be green; flock'd appends; forgery-proof
  entry headers.
- **close.py** — the story-close pipeline: two invocations, one judgment gap;
  review bundle with rules inlined; verdict required and recorded in the merge;
  drift/trunk-motion/dirty guards (mode-matched, tag-proof, origin-aware);
  sprint-integration branching (`release: sprint`).
- **session_start hook** — lead-profile injection: values-first banner, digest
  with staleness stamping, always-current recovery block, repo content inside a
  labeled trust fence, 12k-char structural cap, session-scoped liveness marker.
- **bash_status + stop_gate hooks** — the Stop gate: built against LIVE captured
  payloads (PostToolUseFailure carries the red; PostToolUse implies success);
  overall exit must entail the verify's status (no pipe/subset false greens);
  per-verify markers; advisory block that releases via plan status.
- **Process artifacts** — VALUES (operational: findings cite values, decisions
  name tradeoffs), one-page PROCESS with the review stopping rule and the
  finding bar, reviewer charters with plan-assigned depth, git hooks as the
  unforgeable floor.
- Sprint close ran in full: 21 confirmed cross-cutting findings (6 fixed,
  7 triaged never), security review clean, retro at docs/retros/sprint-001.md.

## v0.1.0 — 2026-08-19 · Sprint 0: the process, hand-built

Marketplace structure, VALUES/PROCESS one-pagers, plan-reviewer and
story-reviewer charters, story-close checklist, lefthook wall, .xp/ planning
artifacts. No code — the artifacts the plugin would later automate.
