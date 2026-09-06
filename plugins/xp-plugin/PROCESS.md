# Process

## Start here

`/xp-setup` once. Run the exact `recover:` command from SessionStart; read
uninjected digest, recovery block and sprint slice. Artifacts win.

## The loop

Every review is named for the artifact it reads:
**slate review** → **card refresh** → **execution plan review** → **diff review**.

Background long legs. No timeout.

1. **Slate review** — `/create-sprint` authors and opens with a fresh reader over
   `sprint_cap`. Mid-sprint: record, never schedule; `[sprint-direct]` keeps work on
   the sprint branch in sprint review; free cuts a patch tag to ship now.
   `spawn.py ready <story-id>` follows the corrected slate; it refuses until
   `slate_review.py --refresh <story-id>` rewrites stale HEAD claims; the lead owns
   this non-review. Multi-file spawn stages a planner, then **execution plan review**
   (`plan_review.py`); the planner writes the plan. Human-only questions stop.
2. **Story** — `spawn.py <story-id>` launches. Red → green → refactor, small commits. Carded story or free work
   stays in its worktree, never in the lead's checkout; practice, not a wall:
   data root proves spawn, not authorship. Done means ACs at the surface.
3. **Story close** — `/story-close`: Diff review, Verify, merge; one full review always.
4. **Sprint close** — `/sprint-close`: falsifiers, full, triage, retro, review; with
   the human, schedule debt under budget or drop it. Nothing carries.
5. **Free** — `close.py free <slug> start`, dated card, spawn, then `/free-close`.

At story/sprint close replace, never append, the ≤30-line session digest.
