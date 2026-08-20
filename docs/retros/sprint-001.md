# Retro — sprint-001 (2026-08-19)

## Delivered
5 stories + 1 bug, 88 tests, ~1,200 lines shipped Python (budget ≤5k), prose share
10% (predecessor: 33%). The plugin now: records work (work.py), closes stories
(close.py, two invocations), injects the lead profile (session_start), and gates
red Verifies at Stop (bash_status + stop_gate) — all consumer-safe after the
broad review's cwd/refusal fixes.

## Keep (value cited)
- **Fresh-context review at every altitude** (Feedback): plan reviews gated 13
  findings pre-code; story reviews found 26 more (8 gating), incl. two classes
  only LIVE PAYLOAD CAPTURE exposed — the shipped gate was inert against
  production, twice. Reviewers who run probes beat reviewers who read.
- **Plan-reviewer-assigned review depth** (Simplicity): deep went exactly where
  it paid (state machines, fail-open hooks); standard sufficed elsewhere.
- **Fault-injection before trusting any test** (Honesty): caught vacuous tests
  at plan stage, red stage, and review stage. Non-negotiable, keep forever.
- **Sprint-close broad review** (Feedback): 21 confirmed cross-cutting findings
  invisible to story diffs; 6 fixed at patch scale, rest triaged NEVER.

## Fix (process changes, all already landed as diffs)
- **Review stopping rule** + faithful=scope-identical + delta-ping: the loop
  converged every story after the rule; one regression shipped from
  scope-widening before it existed (caught in minutes, fixed same day).
- **The finding bar** (Courage/Simplicity — the sprint's biggest lesson, Paul's):
  reviews generate work faster than sprints absorb it; only silent-or-corrupting
  failure modes earn work, loud self-healing corner cases are NEVER. 7 broad-review
  findings reclassified from a sprint's worth of stories to zero.
- **Message-crossing race** (twice: a stand-down crossed a don't-close; a verdict
  crossed a delta request): dissolves when close.py spawns the reviewer
  synchronously — already the Sprint-2 spawn-CLI story.

## Try (Sprint 2)
Spawn CLI (with reviewer spawn-in-pipeline + marker design input from work.md),
/xp-setup scaffold (git hooks + .xp templates + seeds), sprint-close pipeline
(automates what this close did by hand), size-ratchet CI.
