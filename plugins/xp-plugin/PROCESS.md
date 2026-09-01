# Process

## Start here

`/xp-setup` runs once before this loop. Run the exact `recover:` command printed by SessionStart. Read digest,
recovery block and sprint slice; they are not injected. Artifacts win.

## The loop

1. **Card review** — lead reviews slate against `sprint_cap`; free work is
   slotless. `spawn.py ready <story-id>` binds it. For multi-file work, executor
   writes the plan and runs **plan review** with `plan_review.py <story-id> <plan-file>`;
   the lead never writes it. Human-only questions stop.
2. **Story** — `spawn.py <story-id>` launches. Red → green → refactor, small commits. Carded story or free work
   stays in its branch worktree, never in the lead's checkout; practice, not a wall:
   data root proves spawn, not authorship. Done means ACs at the surface.
3. **Story close** — `/story-close`: Review, Verify, merge; one full review always.
4. **Sprint close** — `/sprint-close`: uncovered falsifiers run before full. Triage and retro follow;
   review covers retro. Present it; with the human, schedule debt under budget or
   drop it. Nothing carries.
5. **Free** — `close.py free <slug>`: start, add dated card, cut release artifacts, review, land, post-merge.

Replace the ≤30-line session digest at story/sprint close; never append it.
