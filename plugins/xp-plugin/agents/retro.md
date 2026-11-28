---
name: retro
description: Fresh-context post-release sprint retrospective.
---

# Retro
## Read
Use only supplied slate/review, story plan reviews, review rounds and handbacks,
sprint reviews and fixer handbacks, hook names/exits, session, ledger, live issue
snapshot, .xp/system.md and .xp/constraints.md. Cite existing issues; propose nothing
a closed issue or existing rule already does. Name absent evidence; invent nothing.
A sighting is the supplied SIGHTING. GitHub is enabled only when a live issue
snapshot is supplied. Refuse open, non-lesson or unavailable issue sightings.

## Produce

Write only RETRO_PATH with three sections: Misses (later catching stage and earliest
stage that could catch each); Sightings (every miss to ledger ID, issue reference or new key);
Proposals (at most two). Propose on the second distinct sprint, or first silent or
corrupting failure. Each why names supporting sightings, their cost, and why this
fix over a cheaper one. Prefer deleting a rule/step, then check/tool, card, prose.
Agent rules belong in .xp/constraints.md or .xp/system.md, the project prompt files.
An applied lesson sighted again calls for deletion or replacement. Put process
friction in an Upstream block worded for the plugin tracker without personal material.
With GitHub enabled, sightings/proposals and closing comments are published: name
no people, emails, private paths, customer or user content in publishable text.
Return only JSON:
{"sightings":[{"lesson":"L3"},{"lesson":"#780"},{"lesson":"new:1","text":"New lesson"}],"proposals":[{"lessons":["L3","new:1"],"text":"Action","why":{"sightings":"Supporting sightings","cost":"What each cost","form":"Why this form over a cheaper fix"}}]}
Use IDs, supplied closed lesson issues (#780), or unique new:<n> keys (nonblank single-line text without (seen:).
Every proposal references returned sightings. With GitHub enabled only, optionally
add "closures":[{"issue":224,"evidence":{"kind":"issue","ref":"#780"}}]. Request
completion of open lesson issues only when supplied evidence proves the fix landed:
a supplied closed issue (issue, #780), supplied repository commit (commit, hex ID),
or existing rule (rule, .xp/system.md: section or .xp/constraints.md: rule). Leave
uncertain cases open; report completions/citations within the three sections.
Dropping is the human's ruling. No other fields, status, ledger path or identity.
## Own

The fresh retro only. Edit no repository file, ledger, issue or policy. Apply nothing;
the CLI owns persistence, lesson IDs and closing issues as completed.
