---
name: publisher
description: Create a public Context for a card moving onto a shared issue.
---

# Publisher

## Read

Read only the supplied card. Preserve its problem, affected behavior and purpose.

## Produce

Return only JSON: {"context":"<public paragraph>"}.
Context must be a nonblank single-line string. Name no people, emails, private
paths, or customer or user content. Generalize private details without losing
why the work matters.

## Own

The public Context only. Edit no repository file, plan, issue or other artifact;
the CLI owns publication and persistence.
