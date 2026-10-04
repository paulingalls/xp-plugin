# Judgment

- See red; never fake it. A commit with no red says why in its body. Never bypass hooks.
- **Comments**: restatement or history, delete; WHAT, rename; claim, test. Keep the why, external constraints, rejected designs.
- **Findings** name the code, the cost or failure now, the XP value, and the cheapest sufficient fix. Principles are not proof. Like lines need not duplicate knowledge; no imagined use, no mandatory split.
- **The bar**: a finding earns work when its failure is silent or corrupting: a false green, a corrupted record, an unreviewed merge. A loud failure does not.
- **Design lenses**: responsibilities and boundaries (co-change, interference, exposed internals); contracts and authoritative knowledge (caller promises, rule owners, copies); necessary complexity (required behavior, callers, repeated change).
- **Disposition**: fix by default; drop with a reason; or debt under BOTH bars. Drop a too-big loud finding.
- **Red, green, refactor.** A preparatory change only if safer or simpler here, behavior preserved, existing checks green before and after.
- **New information**: restate the purpose; no drift.
- Escalate choices reserved to the lead. Unmet ACs and release blockers are not waivable. Agents judge; hooks validate.

## Records (`xp.py bug | debt | note | resolve`)
- **bug**: claim, red falsifier, files. Fix now.
- **debt**: claim, green falsifier, files, and BOTH bars: too big (doubles the card, crosses a concern, needs its own design) AND too important (silent, corrupting, privacy, user harm).
- **resolve**: a green falsifier replaces the record's; the lead, at close, on the landed tree.
- **note**: a tradeoff or discovery, never a deferred finding.
