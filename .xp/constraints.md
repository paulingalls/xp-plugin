# Constraints

Reversing one of these makes it a different project. Cap: 15 lines of constraint;
adding over the cap requires retiring one (the plan reviewer enforces).

1. **Every rule must displace one; a CORRECTION displaces nothing** — it creates no NEW
   obligation, only makes an existing one findable or non-contradictory. Size budgets in
   DESIGN §9 are acceptance criteria, measured by ratchet.py at pre-push.
2. **Fault-inject every guard.** A check that cannot red against its target defect is
   vacuous and worse than no check — it certifies. This applies to the plugin's own
   gates, tests, and filed falsifiers. (The predecessor's audit: 7 vacuous guards
   shipped by one agent in one session, zero found by reading.) The inverse breaks a
   gate too: normalize raw wall clock against a same-run control, or use a
   generous HANG GUARD and assert the event.
3. **Independent adversarial pressure, not bookkeeping.** A mechanism must be able to
   tell us something we didn't already believe, or it doesn't ship.
4. **Stdlib only.** No external Python packages, ever. Each dependency is a failure
   point on someone else's machine.
5. **CLI-hook gates are advisory by declaration; hard properties live in git hooks or
   in close.py doing the thing itself.** (Measured: a gated model forged a hook
   marker; six command spellings evade bash-hook detection.)
6. **Telemetry is never a record.** Test/lint failures are re-measured, not filed —
   but green alone / red in parallel is an ISOLATION defect, not telemetry.
7. **Judgment only at LLM-present moments.** Hooks are deterministic Python; nothing
   in a hook may require summarizing, deciding, or interpreting.
8. **Small files: target 300 lines, hard cap 500 — tests included.** Tests are
   production code: the cap and the comment rubric bind tests/ exactly as they
   bind shipped code. Large files eat agent context on every read; over-cap means
   extract, not scroll.
9. **Comments exist only for what neither a test nor a name can carry** — the why,
   an external constraint, a rejected design; JUDGMENT.md gives every role the
   rubric. Prose in code is budgeted like any other prose because a comment is
   the one artifact no test checks, so it rots silently.
10. **Markers are always scoped** (story/plan/session) — a project-global mutable
   marker is a design error (measured: marker bleed between parallel stories).
11. **A falsifier must CONSTRUCT the condition it claims** — never observe ambient
   state, grep for an identifier, or assert a token's presence; and a resolution's
   replacement must COVER the claim, not merely be green, and it names a test by
   NODE ID — `-k` matching nothing exits 5, so it proves only that no test bears
   the name and greens against any later one so named. PIN THE GUARANTEE, never
   the wording or today's flaw: coupled to what code is CALLED or SAYS it reds on
   a rename or a rephrase; coupled to the FLAW it INVERTS, and paying the debt is
   what reds it.
12. **A path we do not execute is not verified.** We are the only user and our tests
   build their own fixtures, so shipped surfaces go unwalked. Before releasing a
   surface a consuming project uses, walk it end to end. PROSE THAT INSTRUCTS AN
   AGENT TO RUN SOMETHING IS SUCH A PATH — run it yourself before shipping the
   instruction (measured: v0.7.7 told two fixers to run a gate that inspects
   nothing over unstaged edits). Walking it costs minutes.
13. **A claim about existing code is CHECKED before it is written down.** A card,
   plan, review, CONFLICT RESOLUTION or PROMOTED note asserting what the code does, without running or
   reading it, spends a story on a premise. Cheap to check, expensive to inherit.
14. **A release is the tag, the manifest and the CHANGELOG naming ONE version.**
   `plugin.json`'s version keys the consumer's plugin cache, so a tag that moves
   without it ships the previous cached copy under the new name — silently, and to
   everyone except us (measured: v0.6.0 tagged with the manifest at 0.5.0, surfaced
   by a field report still running "0.3.0"). Bump the manifest and write the entry
   in the release commit, before the tag; tests/test_release.py is the wall (constraint 5).
15. **Distinct states stay distinct.** Never infer one state only from the absence
   of another. Missing is not unreadable; retired is not unfinished. Enumerate
   terminal and active states, and fault-inject every refusal boundary between them.
