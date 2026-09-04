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
   covered and cost one confirming round. Apply the finding bar in JUDGMENT.md.
3. **Land**: `close.py free <slug> land` opens the release PR.
4. **After merge**: `close.py free <slug> post-merge` tags.
