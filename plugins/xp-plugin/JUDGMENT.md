# Judgment

- Red first; watch it fail. Never fake a red; no-red commits say why. Hooks are the
  wall: your commit and push hooks run the tiers you configured. Never bypass
  them.
- **Comments** — restates the code → delete · explains WHAT → rename it ·
  a checkable claim → write the test · narrates history → delete, git holds it.
  Keep only the why, external constraints or rejected designs.
- **Review** — Generalization, uncovered behavior or resolved conflict = deviation
  owed a round. Bar: silent or corrupting (false green, corrupted
  record, unreviewed merge) earns a round; loud does not.

## Records (`work.py` only)

- **bug** — claim + red falsifier + files; fix now. No red=debt/note.
- **debt** — claim + green falsifier + files; planning schedules/archives.
- **resolve** — substitutes a green falsifier; ids: `work.py list`.
- **coverage** — optional `--covered-by TIER`; tier-selection claim is unchecked;
  resolutions redeclare.
- **note** — value tradeoff or discovery; close promotes/archives; next-story
  directives go on card.
- **Polarity** — debt: green = still OK; red = materialised; green from the flaw =
  inverted.

Telemetry: re-measure, never record.
