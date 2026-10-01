# Process

## Start here

`/xp-setup` once; run the exact `recover:` command. Its first region
is next; artifacts win.

## The loop

Every review is named for the artifact it reads:
**slate review** → **card refresh** → **execution plan review** → **diff review**.

Background long legs. No timeout.

1. **Slate review** — `/create-sprint` authors and opens with a fresh reader over
   `sprint_cap`. Mid-sprint: record, never schedule; `[sprint-direct]` stays on
   the sprint branch in sprint review; free work can ship now.
   `spawn.py ready <story-id>` follows the corrected slate only after
   `slate_review.py --refresh`; the lead owns that non-review. Multi-file: the planner writes the plan
   before **execution plan review** (`plan_review.py`). Human-only questions stop.
2. **Story** — `spawn.py <story-id>`; red → green → refactor, small commits. Carded/free work stays
   in its worktree; data root proves spawn, not authorship. Done means surface ACs.
3. **Story close** — `/story-close`. One full review always.
4. **Sprint close** — `/sprint-close`. With the human, judge all open debt/findings:
   fix, reasoned drop or exceptional keep under BOTH JUDGMENT bars. Debt budget
   is a ceiling; nothing carries unjudged.
5. **Free** — `close.py free <slug> start`, then `/free-close`; slotless, ships now.

Close replaces the ≤30-line session digest.
