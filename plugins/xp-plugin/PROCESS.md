# Process
`/xp-setup` once; exact `recover:` command; first region next; artifacts win.
Every review is named for the artifact it reads:
**slate review** → **execution plan review** → **diff review**.
Background long legs. No timeout.
1. **Slate review** — `/create-sprint` opens; one fresh reader; `sprint_cap` advises the lead. Apply review corrections, then open; opening only records the sprint and runs its lifecycle. Mid-sprint: record, never schedule; `[sprint-direct]`: sprint branch, sprint review; free: ship now. Launch `[planned]` work directly with `spawn.py <story-id>`. Multi-file: the planner checks current code and owns the plan; one independent plan review corrects it within approved intent. Accepted corrections proceed directly. Human-only questions stop.
2. **Story** — `spawn.py <story-id>`; red → green → refactor; small commits. Carded/free work stays in its worktree; data root proves spawn, not authorship. Done: surface ACs.
3. **Story close** — `/story-close`; one full review.
4. **Sprint close** — `/sprint-close`: with human, judge all debt/findings per JUDGMENT; debt ceiling.
5. **Free** — `close.py free <slug> start`, then `/free-close`: slotless; ship now.
Close replaces ≤30-line session digest.
