# Judgment

- Watch red first; never fake it. No-red commits say why. Never bypass hooks.
- **Comments** — restatement/history → delete · WHAT → rename · claim → test.
  Keep why, external constraints or rejected designs.
- **Review** — Generalization, uncovered behavior or resolved conflict owes a
  round when silent or corrupting (false green, corrupted record, unreviewed merge);
  loud does not.
- **New information** — restate what work is FOR before choosing; no goal drift.

Fix by default; explicitly drop with a reason or keep debt under BOTH bars.
Too-big loud findings announce themselves: drop. Escalate reserved choices.
ACs/blockers cannot be waived. LLMs judge; hooks validate structure.

## Records (`work.py` only)

- **bug** — claim + red falsifier + files; fix now. No red: judge.
- **debt** — claim + green falsifier + files; BOTH too big (doubles the card,
  crosses its concern, or needs separate design) AND too important
  (silent/corrupting, privacy or user harm). `debt` and renewed `keep --ref ID`
  restate reasons via `--too-big` and `--too-important`.
- **resolve** — substitute green falsifier; lead only, at close, on landed tree.
- **coverage** — optional TIER for bug/debt; resolve: required TIER|none. Selection
  stays UNCHECKED; only tier pins are.
- **note** — tradeoff/discovery, never deferred findings; promote/archive at close;
  next-story directives on card.
- **Polarity** — debt: green = still OK; red = materialised; green from flaw = inverted.

Telemetry: re-measure, never record.
