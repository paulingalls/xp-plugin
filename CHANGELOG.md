# Changelog

## v0.4.0 — 2026-08-21 · Sprint 3: the close runs itself

The sprint close stopped being hand-composed. That is the release.

- **`close.py sprint <id> review --lens broad|security`** marshals the sprint's
  reviews the way the story close already marshalled its one: same bundle, same
  `{fixed, blocking, noted}` shape, and a MODE SWITCH — findings handed in bound
  the next round to validating them, none means run the full pass. Sprint-002
  hand-composed both prompts and then re-reviewed four fix-commits with nothing
  to bound the pass. **Sprint land refuses** unless both lenses cover HEAD with
  no blocking findings; a release PR over unreviewed commits was bug c9b48a66,
  measured on a real release.
- **`ratchet.py` measures the size budgets at pre-push** — per-component lines
  and comment density against DESIGN §9, on a live number rather than a
  remembered one. It caught a density breach the day it shipped. It measures the
  SHIPPED plugin, so it lives outside it: nothing under `plugins/xp-plugin/`
  exists for our benefit rather than a consuming project's, and a test now
  refuses any shipped script nothing imports or invokes.
- **`land` finishes the job from a worktree.** It preflights whether another
  tree holds the integration branch, merges there, then removes the worktree and
  deletes the branch remote-first — `-d` compares against the upstream ref, so
  local-first refused a branch already merged to HEAD and printed a remediation
  that could not work. The structural check moved above the test run: landing
  used to spend ~2 minutes of tests to reach a `git worktree list` comparison.
- **`work.py archive`** gives a triage decision somewhere to live. Sprint 1
  genuinely triaged and the decision was indistinguishable from an untriaged
  note, so the emission only ever grew — 75 records at this close, 53 predating
  the sprint. Now 3. Bugs are refused: a bug's falsifier reds now, so archiving
  one hides a live defect.
- **A teammate's transcript is durable and live** (`~/.xp/data/<id>/logs/`), and
  the spawn refuses a handback that leaves work uncommitted or makes no commits
  of its own.
- **Prose that describes a mechanism is gone from the skills.** A SKILL says what
  to run, what you own, and how to respond; mechanism lives in the code and
  remediation in the refusal text. Both close skills shrank by ~40%.

Constraints 11 and 13: a falsifier names a test by NODE ID (a `pytest -k`
matching nothing exits 5, so it is red only for lack of a name and greens against
any later test given it), and a claim about existing code is CHECKED before it is
written down.

## v0.3.0 — 2026-08-20 · Sprint 2: the process runs itself

The reviewer stopped reporting and started **fixing**. That is the release.

Measured on the two halves of the same redesign, same model, same story size:
under a reporting reviewer story-012a took **4 review rounds and 11 blocking
findings** and never converged; under a fixing reviewer story-012b took **1
round — 7 fixed, 0 blocking**. The round-trip was the cost, not the reviewing.

- **The reviewer fixes in the tree under review** and commits under its own git
  identity, which is a GATE: any commit in the range it did not author means
  unreviewed work would ride the merge, so review refuses. That also permits the
  lead to keep working during a review instead of tripping a guard.
- **Review and merge are separate commands.** `land` is deterministic, mutates
  only refs, and never spawns — it refuses on blocking findings, on HEAD moving
  since the review you were shown, or on a round that does not cover the merge
  base. Story-008's land ran four times, spawned four reviewers, and merged
  nothing; that shape is gone.
- **A structured `{fixed, blocking, noted}` report** replaces the VERDICT line
  the pipeline used to grep — forgeable by design, then defeated by backticks.
  It fixes parsing, not forgery, and the prose says so.
- **Records are named and can be resolved.** An ISO second is not a name (48
  concurrent appends produce 48 identical headings), so ids are derived from
  entry text — which works retroactively on an append-only file. A resolution
  SUBSTITUTES a falsifier that must be green now, so a wrong one reds later and
  the record reopens.
- **`sprint start` / `land` / `post-merge`** automate the sprint close: full
  tier, the falsifier batch, note triage, the retro skeleton. The tag is cut
  post-merge on the sha that actually shipped, never at PR-open.
- **`/xp-setup`** scaffolds `.xp/` and the git-hook wall, and the first-user path
  is now walked rather than only tested.
- Prose in code is budgeted (≤20% of shipped Python) with the rubric shipped in
  PROCESS.md, TEAMMATE.md and the reviewer charter, pinned identical.

Fixed at the release gate, none of it findable from inside a story: `release:
sprint` could not work in a scaffolded repo, the first spawn after `xp-setup`
tracebacked, and two `work.md` fields could forge records past the falsifier
green-check.

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
