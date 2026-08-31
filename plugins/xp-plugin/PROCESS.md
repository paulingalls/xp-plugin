# Process

## Start here

Run the exact `recover:` command printed by SessionStart. Read digest,
recovery block and sprint slice; they are not injected. Artifacts win.

## The loop

`/xp-setup`, `/story-close` and `/sprint-close` carry judgment; scripts own mechanics.

1. **Card review** — lead reviews slate against `sprint_cap`; free work is
   slotless. `spawn.py ready <story-id>` binds it. For multi-file work, executor
   writes and runs the **plan review**; the lead never writes it. Human-only questions stop.
2. **Story** — red → green → refactor, small commits. Carded story or free work
   stays in its branch worktree, never in the lead's checkout; practice, not a wall:
   data root proves spawn, not authorship. Done means ACs at the surface.
3. **Story close** — Review, Verify, merge; one full review always. A reviewer fix
   is inside the round that found it; a lead fix moves HEAD past what the review
   covered and costs a confirming round.
4. **Sprint close** — Uncovered falsifiers run before full. Triage and retro follow;
   review covers retro. Present it; with the human, schedule debt under budget or
   drop it. Nothing carries.
5. **Free** — `free start`; add dated card, cut release artifacts, review, land, post-merge.

Replace the ≤30-line session digest at story/sprint close; never append it.
