# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

xp-plugin: a lightweight XP process plugin for coding agents (Claude Code + Codex),
the successor to ../xp-agents. We **dogfood the process while building it** — this
repo runs under the same artifacts the plugin will ship. docs/AUDIT.md (evidence)
and docs/DESIGN.md (architecture and completed build record) are
the authorities; don't re-litigate settled decisions, propose diffs to them
instead.

## The process, enforced

- **Slate review**: before sprint open one fresh `slate-reviewer` reads the whole slate;
  capacity advises the lead, who judges every result and applies corrections.
  Addressed findings need no automatic second review; opening only runs its
  lifecycle and records branch/membership;
  `spawn.py <story-id>` launches planned work directly. The planner checks current
  code and owns the implementation plan; one independent plan reviewer corrects
  correctness within approved intent. Accepted corrections proceed to execution;
  human-only questions preserve corrections and return to the lead.
  Red test first; for config/docs commits, never fake a red — say so in the commit body.
- Story done → run the `/story-close` checklist (spawns `story-reviewer`).
- Records (bug/debt/note) per JUDGMENT.md; mid-sprint you may record, never schedule.
- Git hooks (lefthook) are the wall: ruff + gitleaks + fast tests at commit, story
  tier at push, full tier at sprint land. Don't bypass them (`--no-verify` is a
  values violation, not a trick).

## Commands

- Test tiers live in `.xp/config.yml` — read them there and run those spellings
  verbatim, xdist flag included. Serial pytest is ~6x slower, and the worker count
  is a measured choice per tier, not a default (sprint-10 retro). Restating a tier
  here is a fourth copy that drifts the day one is retuned; it already did.
- Lint: `ruff check --fix . && ruff format .`
- Hooks: `lefthook install` (once per clone)

## Running the close legs (this repo's lead, learned at Sprint 9)

NEVER PIPE a `close.py` leg. A pipe reports the PIPE's exit status, so the leg's own
refusal reads as success, and block buffering swallows its last line — measured: two
completed review rounds died mid-commit reading as "exit code 0", and the note I filed
blamed the pipeline before I proved it was mine (75842bb4, corrected by de7bc1aa).
Redirect to a file and read it: `close.py ... > /tmp/leg.txt 2>&1; echo "rc=$?"`.
PROCESS.md's "background every long leg" is `run_in_background: true` on the Bash
call, set from the FIRST call, with no explicit timeout.

## Size discipline

At close, run `python3 tests/scripts/ratchet.py`, read its table, and give the
measured component and density values to the reviewer as guidance. They report;
they do not refuse growth. Constraint 8's 500-line hard cap remains structural,
tests included. The report measures the SHIPPED plugin, so it lives outside it:
nothing under `plugins/xp-plugin/` may exist for our benefit rather than a
consuming project's. Our cards carry a `Spend:` line the shipped card shape has
no field for — the ratchet component, the declared files' counts, and any
extraction the card must make first. It is a claim about existing code, so
re-measure it during planning. This rule lives HERE because `Spend`, components
and extraction are ours; a consuming project's planner has its own constraints.
Every added rule displaces one. When in doubt: VALUES.md;
conflicts resolve Honesty > Courage > Simplicity > Feedback > Communication.

## Authoring skills (ours, not a consuming project's)

A SKILL driving a script says what to run, what you own, and how to respond to
results. Mechanism lives in the code and remediation in the refusal text, so
describing either ships a second copy that only drifts. Negative space — what
deliberately does not exist — is the one description that earns its words.
This only works if the script speaks: every refusal names its next action, and
every CLI answers `--help` without doing anything.
