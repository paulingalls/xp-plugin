---
name: sprint-close
description: >-
  Close the sprint: full tier, falsifier batch, note triage, retro diff, release.
---

# Sprint Close

`close.py sprint <id>` runs the mechanical steps. Two of them are yours and a
script cannot absorb them (judgment belongs only where an LLM is present).

0. **Open the sprint first** (once, before its stories): `git switch -c sprint-00N`,
   then `close.py sprint <id> start`. It records and prints this clone's branch;
   unfinished output says close checks wait.
1. **Re-run `close.py sprint <id> start` at close** — the same recorded branch is
   a no-op; now it runs the batch and emits the close material.
   A red falsifier ABORTS the close and is re-filed as a bug (PROCESS.md carries
   the polarity contract).
2. **Note triage, then the retro — YOURS, and they come FIRST.**
   Each note is promoted to constraints.md/system.md via the retro diff, or
   archived. A learning that changes nothing executable is not recorded, and every
   promotion must displace something (every new rule displaces one). Then write the retro
   narrative and REPLACE the digest: the pipeline emits facts, the
   narrative is the part with judgment in it.
   BEFORE the review, not after. Land refuses when code moved since the review,
   and a retro that promotes into DESIGN.md or PROCESS.md is code motion — run it
   last and you must review again, which invalidates what you just wrote.
3. **The review**, which the pipeline marshals — you do not compose it:
   `close.py sprint <id> review`. It finds, judges, fixes and clears in one
   command; what reaches you is what it could not fix. Fix that, then re-run.
   Read the reviewer's diff before you land: running land is how you accept it.
4. **`close.py sprint <id> land`** opens the release PR. Not releasable? Don't run
   it — the branch carries.
5. **`close.py sprint <id> post-merge`**, AFTER the PR merges — it tags. Your
   release artifacts are yours;
   cut them at step 2, before review, because later code motion invalidates it.
