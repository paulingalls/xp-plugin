# Process

## Start here

`/xp-setup` once. Run the exact `recover:` command from SessionStart; read
uninjected digest, recovery block and sprint slice. Artifacts win.

## The loop

Every review is named for the artifact it reads:
**slate review** → **card refresh** → **execution plan review** → **diff review**.

1. **Slate review** — `/create-sprint` authors, then `/sprint-close` runs
   a fresh reader over the full slate and `sprint_cap`; free work
   slotless. The corrected slate precedes
   `spawn.py ready <story-id>`. For multi-file work, executor writes the plan and
   runs **execution plan review** with `plan_review.py <story-id> <plan-file>`; the lead never
   writes it. Human-only questions stop.
2. **Story** — `spawn.py <story-id>` launches. Red → green → refactor, small commits. Carded story or free work
   stays in its worktree, never in the lead's checkout; practice, not a wall:
   data root proves spawn, not authorship. Done means ACs at the surface.
3. **Story close** — `/story-close`: Review, Verify, merge; one full review always.
4. **Sprint close** — `/sprint-close`: uncovered falsifiers precede full. Triage and retro follow;
   review covers retro. With the human, schedule debt under budget or
   drop it. Nothing carries.
5. **Free** — `close.py free <slug>`: start, add dated card, cut release artifacts, review, land, post-merge.

Replace the ≤30-line session digest at story/sprint close; never append it.
