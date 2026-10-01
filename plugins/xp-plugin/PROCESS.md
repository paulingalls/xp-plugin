# Process
`/xp-setup` once; exact `recover:` command; first region next; artifacts win.
Every review is named for the artifact it reads:
**slate review** → **card refresh** → **execution plan review** → **diff review**.
Background long legs. No timeout.
1. **Slate review** — `/create-sprint` opens; fresh reader: `sprint_cap`. Mid-sprint: record, never schedule; `[sprint-direct]`: sprint branch, sprint review; free: ship now. Lead non-review `slate_review.py --refresh`; then `spawn.py ready <story-id>`: corrected slate. Multi-file: the planner writes the plan; then `plan_review.py`. Human-only questions stop.
2. **Story** — `spawn.py <story-id>`; red → green → refactor; small commits. Carded/free work stays in its worktree; data root proves spawn, not authorship. Done: surface ACs.
3. **Story close** — `/story-close`; one full review.
4. **Sprint close** — `/sprint-close`: with human, judge all debt/findings per JUDGMENT; debt ceiling.
5. **Free** — `close.py free <slug> start`, then `/free-close`: slotless; ship now.
Close replaces ≤30-line session digest.
