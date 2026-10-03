---
name: sprint-close
description: >-
  Reconcile delivered scope, judge integration, validate the shipping tree and release.
---

# Sprint Close

`xp.py sprint <id>` runs mechanics; the lead owns judgment and release readiness.

1. Triage current bugs, debt and unresolved findings: fix, explicitly drop with a
   reason, or retain exceptional debt with both JUDGMENT.md bars using `work.py keep`.
   For unjudged historical findings, use `work.py judge --source '<marker-path or
   closes.jsonl:LINE>' --report /absolute/judgment.json`. Historical reports stay
   readable; settled judgments are context. Unmet ACs and blockers cannot be waived.
   Judge notes as discovery/tradeoff or findings, then promote or archive explicitly.
   Write the narrative retro/digest under the external XP data root. It can follow
   review. Narrative learning need not become executable policy. Review actual code,
   gate or agent-instructing policy changes before shipping, or explicitly defer
   them without shipping those changes. A filename or narrative label proves nothing.
   Prepare the project-owned release artifacts before review.
2. Run `xp.py sprint <id> review`. Read the emitted preparation facts and refusals. Independent angle readers judge integration
   across delivered stories. Read every disposition and correction diff. Authorized
   findings buy one committing fixer and one narrow closer; a clean result buys
   neither. Remaining findings or an interrupted producer return to the lead.
   Inspect preserved work and reports; correct the solution, then explicitly run
   `xp.py sprint <id> review` for the changed integration. Never retry unchanged
   work to buy an automatic quality round. Do not reopen settled story reviews.
3. When ready, run `xp.py sprint <id> land`. It validates and prepares the release
   PR. The configured full tier owns release coverage; resolved records add no recurring
   commands. A prepared PR is not a released sprint.
4. After the PR actually merges, check out the intended trunk and run
   `xp.py sprint <id> post-merge`. It validates the actual shipping tree and
   finishes the release. Follow refusals; do not treat missing evidence as green.
