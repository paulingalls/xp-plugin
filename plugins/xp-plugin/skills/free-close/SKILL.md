---
name: free-close
description: >-
  Close a free patch: release boundary, review judgment, confirming round.
---

# Free Close

The scripts own the mechanics. You own the judgment.

1. **Release boundary**: Your release artifacts are yours; cut them before review.
2. **Review**: Read the round `spawn` recorded and the reviewer's diff; re-run
   `close.py free <slug> review` only if the tree moved. The reviewer's fixes
   stay inside the round that found them. Your fixes move HEAD past what the review
   covered and cost one confirming round. Exception: when a completed review's
   Verify redded without blocking findings, fix only reviewed or card Files paths,
   commit, then run `close.py free <slug> repair`; a bounded repair passing Verify
   owes no confirming round. Apply the finding bar in JUDGMENT.md.
   If land measures a Verify or tier red after a recorded round with no blocking
   finding, fix only reviewed or card Files paths, commit, run
   `close.py free <slug> repair`, then `close.py free <slug> land` again. This bounded
   land-time repair also owes no confirming round. Other lead fixes still do.
3. **Land**: `close.py free <slug> land` opens the release PR.
4. **After merge**: `close.py free <slug> post-merge`.
