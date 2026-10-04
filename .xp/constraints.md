# Constraints

Reversing one of these makes it a different project. Cap: 10 items; adding one
retires one. Reviewers enforce these and cite the item. A rule a hook or the
plugin already enforces is a second copy: delete it.

1. **Test behavior at the outermost boundary that reaches it, once.** When an
   integration or acceptance test covers a behavior, delete the unit tests that
   duplicate it. Unit tests are TDD scaffolding, not a permanent asset.
2. **Tests cost what code costs.** Test lines stay at or below twice the shipped
   lines and shipped Python stays under 4,000; `tests/scripts/ratchet.py` is the
   wall. The commit hook finishes in under a minute.
3. **A guard is fault-injected once, when it is added, in its own test file,
   and only if its failure would be silent or corrupting.** No tests of tests,
   no meta-tests of gates. A loud failure needs no guard at all.
4. **Small files: target 300 lines, hard cap 500, tests included.** Extract,
   do not scroll.
5. **Comments carry only what a test or a name cannot**: the why, an external
   constraint, a rejected design. Restates the code or narrates history: delete.
6. **Fail fast, fail loud.** Raise instead of returning None or empty; no
   fallback that masks a defect.
7. **Run it before you write it down.** A plan, card, review or decision that
   claims what code does has read or executed that code first.
8. **Walk every shipped path before release.** A test fixture does not verify
   a user-facing or agent-instructed path; execute it end to end on both
   harnesses.
9. **Stdlib only.** No external Python packages; each is a failure point on a
   consumer's machine.
10. **Delete before you add.** A field failure is answered first by removing a
    mechanism; a card that adds one states why deletion cannot fix it.
