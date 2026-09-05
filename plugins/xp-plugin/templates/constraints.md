# Constraints

Reversing one of these makes it a different project. Cap: 15 items; adding over
the cap requires retiring one. Reviewers enforce these — cite the item.

1. **Fault-inject every guard.** A check that cannot red against its target
   defect is vacuous and worse than no check — it certifies.
2. **Small files: target 300 lines, hard cap 500 — tests included, because
   tests ARE production code**: same review bar, never skipped for test-only
   changes. At or before the cap, extraction needs no separate approval:
   before/after collection counts match and every collected test passes. Large
   files eat agent context; extract, do not squeeze or scroll.
3. **Comments exist only for what neither a test nor a name can carry** — the
   why, an external constraint, a rejected design. Restates the code → delete.
   Narrates history → delete (git holds it). Checkable claim → make it a test.
4. **Fail fast, fail loud** — raise instead of returning None/empty when
   something is wrong; no fallback that masks a defect.
5. **Test at boundaries** — validate at system edges (input, APIs, I/O); trust
   internal logic.
6. **Require independent challenge**: a check or review must be capable of
   disagreeing with the premise it examines, not merely repeat its author.
7. **Walk shipped paths**: a substitute does not verify a user-facing or
   instructed path. Execute each changed path end to end before release.
8. **Check behavior claims first**: read or run existing behavior before a
   plan, review, or decision relies on a claim about it.
9. **Name one release version**: before publication, the tag, package or
   manifest metadata, and release notes must name the same version.
10. **Keep states distinct**: never infer one state only from another's
    absence. Represent active and terminal states, and test refusal boundaries
    between them.
