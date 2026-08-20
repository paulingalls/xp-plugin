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
8. **Markers are always scoped** (story/plan/session) — a project-global mutable
   marker is a design error (measured: marker bleed between parallel stories).
