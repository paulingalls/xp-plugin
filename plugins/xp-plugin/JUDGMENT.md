# Judgment

- Red first; watch it fail. Never fake a red; no-red commits say why. Hooks are the
  wall: your commit and push hooks run the tiers you configured. Never bypass
  them.
- **Comments** — restates the code → delete · explains WHAT → rename it ·
  a checkable claim → write the test · narrates history → delete, git holds it.
  Keep only the why, external constraints or rejected designs.
- **Review** — Generalization, uncovered behavior or resolved conflict is a
  deviation, owed a round when silent or corrupting (false green, corrupted
  record, unreviewed merge); loud does not.
- **New information** — step back before the next step: restate what the work is
  FOR, then choose. Continuing from what survives a finding is how work drifts off
  the goal that filed it.

## Records (`work.py` only)

- **bug** — claim + red falsifier + files; fix now. No red=debt/note.
- **debt** — claim + green falsifier + files; planning schedules/archives.
- **resolve** — substitutes a green falsifier; lead closes on landed tree; ID=`list`.
- **coverage** — optional TIER for bug/debt; resolve: required TIER|none. The
  selection claim stays UNCHECKED; only tier pins are.
- **note** — value tradeoff or discovery; close promotes/archives; next-story
  directives go on card.
- **Polarity** — debt: green = still OK; red = materialised; green from the flaw =
  inverted.

Telemetry: re-measure, never record.
