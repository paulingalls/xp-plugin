---
name: free-close
description: >-
  Close a free patch: release boundary, one-pass review and lead judgment.
---

# Free Close

The scripts own the mechanics. You own the judgment: fix every finding by
default, explicitly drop with a reason, or retain exceptional debt by real record
reference with both JUDGMENT bars. Judge legacy/untriaged findings too. Unmet ACs
and release blockers cannot be waived; escalate reserved choices.

1. **Release boundary**: Your release artifacts are yours; cut them before review.
2. **Review**: Read the retained reports and judge remaining findings under JUDGMENT.
   Commit lead corrections, then explicitly run `close.py free <slug> review`.
   That command also corrects incomplete producer output while retaining earlier
   stages and commits. Use `spawn.py resume <free-id>` for interrupted validation.
   Inspect retained red/green evidence before recording a same-tree disposition
   with `close.py free <slug> acknowledge-validation --reason '<observed cause>'`.
   The sequence runs one independent solution review, one conditional committing
   fixer and one conditional narrow closer. Remaining problems belong to the lead.
3. **Land**: `close.py free <slug> land` opens the release PR.
4. **After merge**: `close.py free <slug> post-merge`.
