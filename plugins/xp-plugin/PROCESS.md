# Process

## Start here

Run the exact `recover:` command printed by SessionStart. Read digest,
recovery block and sprint slice; they are not injected. Artifacts win.

## The loop

`/xp-setup`, `/story-close` and `/sprint-close` carry judgment; scripts own mechanics.

1. **Card review** — the lead reviews the open slate against `sprint_cap`;
   free work spends no slot. `spawn.py ready <story-id>` binds it.
   For multi-file work, the executor writes and runs the **plan review**; the lead
   never writes it. Human-only questions stop.
2. **Story** — red → green → refactor, small commits. Carded story and free work
   is written in its branch's worktree, never in the lead's checkout — practice, not
   a wall: the data root proves spawn, not authorship. Done means ACs at the surface.
   Git hooks are the wall: lint, secrets and fast tests at commit; full tests and
   ratchet at push. Never bypass or fake a red; prose/config-only commits name why
   no red exists.

   Comments: restates the code → delete · explains WHAT → rename it · a checkable
   claim → write the test · narrates history → delete, git holds it. Keep only the
   why, an external constraint, a rejected design.
3. **Story close** — Review, Verify, merge; one full review always. A reviewer fix
   is inside the round that found it; a lead fix moves HEAD past what the review
   covered and costs a confirming round. A deviation — generalizing a
   prescription, uncovered behavior, a conflict you resolved — is owed a round.
   The bar: silent or corrupting (false green, corrupted record, unreviewed merge)
   earns a round; loud does not.
4. **Sprint close** — Uncovered falsifiers precede the full tier. A record declaring
   `--covered-by full` trusts only that tier's green verdict and is named; absent or
   red means its command runs. Triage and retro follow; review covers the retro. Present it;
   with the human, schedule debt under budget or drop it. Nothing carries.
5. **Free** — scope one patch, then `free start`; cut release artifacts, then run free review, land and post-merge.

## Records (`work.py` only)

- **bug** — claim + red falsifier + files; fix now. No red means debt/note.
- **debt** — claim + green falsifier + files; planning schedules/archives it.
- **resolve** — substitutes a green falsifier; ids come from `work.py list`.
- **coverage** — optional `--covered-by TIER`: YOU assert the falsifier is one of
  that tier's selections and nothing checks you. Resolutions declare anew.
- **note** — value tradeoff or discovery; sprint close promotes or archives it.
  A directive the NEXT STORY must follow goes on that card — a note reaches it never.
- **Polarity** — a debt's falsifier: still OK; red means the latent problem
  materialised. A falsifier green because the flaw exists is inverted.

Telemetry is re-measured, never recorded. Replace the ≤30-line session digest at
story/sprint close; never append it.
