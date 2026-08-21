# Constraints

Reversing one of these makes it a different project. Cap: 15 lines of constraint;
adding over the cap requires retiring one (the plan reviewer enforces).

1. **Every rule must displace one.** New prose, hooks, or checks land only by removing
   equal weight. The size budgets in system.md are CI-enforced acceptance criteria.
2. **Fault-inject every guard.** A check that cannot red against its target defect is
   vacuous and worse than no check — it certifies. This applies to the plugin's own
   gates, tests, and filed falsifiers. (The predecessor's audit: 7 vacuous guards
   shipped by one agent in one session, zero found by reading.)
3. **Independent adversarial pressure, not bookkeeping.** A mechanism must be able to
   tell us something we didn't already believe, or it doesn't ship.
4. **Stdlib only.** No external Python packages, ever. Each dependency is a failure
   point on someone else's machine.
5. **CLI-hook gates are advisory by declaration; hard properties live in git hooks or
   in close.py doing the thing itself.** (Measured: a gated model forged a hook
   marker; six command spellings evade bash-hook detection.)
6. **Telemetry is never a record.** Test/lint failures are re-measured, not filed.
7. **Judgment only at LLM-present moments.** Hooks are deterministic Python; nothing
   in a hook may require summarizing, deciding, or interpreting.
8. **Small files: target 300 lines, hard cap 500.** Large files eat agent context
   on every read; over-cap means extract, not scroll.
9. **Comments exist only for what neither a test nor a name can carry** — the why,
   an external constraint, a rejected design. Restates the code → delete. Narrates
   history → delete (git holds it). Checkable claim → convert to a test, where it
   rots loudly. (xp-agents reached 33% prose-in-code with no counter-pressure;
   the rubric is necessary-but-sufficient, same as all prose.)
10. **Markers are always scoped** (story/plan/session) — a project-global mutable
   marker is a design error (measured: marker bleed between parallel stories).
11. **A falsifier must CONSTRUCT the condition it claims** — never observe ambient
   state, grep for an identifier, or assert a token's presence; and a resolution's
   replacement must COVER the claim, not merely be green. (Five instances in
   sprint-002, two of them filed at the sprint close itself: a falsifier coupled to
   what the code is CALLED reds when someone renames it and greens when the defect
   returns under a new name.)
12. **A path we do not execute is not verified.** We are the only user and our tests
   build their own fixtures, so shipped surfaces go unwalked. Before releasing a
   surface a consuming project uses, walk it end to end. (Sprint-002: `release:
   sprint` could not work in any scaffolded repo, the first spawn tracebacked, and
   the installed build predated half the project. Walking it cost ten minutes.)
