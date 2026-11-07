# Judgment

- See red; never fake it. A commit with no red says why in its body. Never bypass hooks.
- **Comments**: delete restatement/history; rename WHAT; test claims. Keep why, external constraints, rejected designs.
- **Findings** name code, current cost or failure, XP value, cheapest sufficient fix. Principles aren't proof. Like lines needn't duplicate knowledge; no imagined use or mandatory split.
- **The bar**: work for silent or corrupting failures (false green, corrupted record, unreviewed merge), or certain or likely failures on the ordinary path in production (every run or common real input). Loud excuses only rare failures.
- **Disposition**: fix by default; drop with reason; or debt under BOTH bars. Loud drops require rarity AND a too-big fix. No deferred production checks ("watch for it in production"): fix or debt.
- **Red, green, refactor.** A preparatory change only if safer or simpler here, behavior preserved, existing checks green before and after.
- **Tests**: outermost boundary reaching behavior; integration over unit; delete covered units. Commit-hook tests: under a minute; slower: push, sprint or nightly. Fault-inject new guards once, only for silent or corrupting failures.
- **New information**: restate the purpose; no drift.
- Escalate choices reserved to the lead. Unmet ACs and release blockers are not waivable. Agents judge; hooks validate.

## Records (`xp.py bug | debt | note | resolve`)
Mid-sprint, record; never schedule.
Gitleaks checks secrets, not personal content.
- **bug**: claim, red falsifier, files. Fix now.
- **debt**: claim, green falsifier, files, BOTH bars: too big (doubles card, crosses concern, needs own design) AND too important (silent, corrupting, privacy, user harm).
- **resolve**: a green falsifier replaces the record's; the lead, at close, on the landed tree.
- **note**: a tradeoff or discovery, never a deferred finding.
