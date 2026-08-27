# Sprint 9 retro — the profile fits the transport, and the unit was wrong

Five cards landed: 058, 055, 053, 060 and 061 — the last two scheduled mid-sprint by
Paul, one to unblock the close and one on a bug he hit while trying to run two sprints
at once. Milestone 4's two open clauses are closed: no leg costs the same for a
confirmation as for a sweep (058), and every role the plugin ships has now been
executed by us (055 for the lead, 053 for the four review stages).

## 1. What the process caught

**A record from August 20th stopped a release on August 27th.** Bug 88b3ce55 —
"SessionStart injects ZERO constraint items into the lead profile" — went red at the
sprint-close batch because story-055's new cap made its claim true again. Nothing else
in the pipeline was watching delivery; the batch was, because a record outlives its
first fix. That refusal is what produced story-060.

**Constraint 12 paid three times in one sprint.** Story-060's reviewer walked the
shipped `recover` instruction on the real repo, where the card's own test walks a toy
fixture that fits, and found it cutting three of four cards. Story-061's reviewer
walked SKILL.md step 0/1 end to end in a scratch repo. Story-055's reviewer reproduced
an empty-profile hook against an unwritable data root. Every finding came from
executing a path, none from reading it.

**Constraint 11's node-id rule made two stale records fail loudly.** Records 37187713
and d3685f4d named test node ids that the fixes closing them had deleted or renamed.
Under the old `-k` spelling both would have matched nothing and gone green; as node
ids they red at the batch and were re-filed as bugs, which is exactly the direction
story-057 built.

**Plan review found what round 1 could not.** Story-055's second plan review raised
close review to deep and produced the sprint's sharpest constraint-2 finding: fault
-inject `OUTPUT_CAP` downward and every fit check stays green, because they all assert
only that the profile FITS and dropping more always satisfies that. The delivery guard
in story-060 exists because of that round.

## 2. What it missed

**The unit, and no mechanism was positioned to ask.** Story-055 shipped
`CODEX_RETAINED_TOKENS = 2_458` and a chars-per-token floor, derived from six
truncated payloads. The artifact says bytes: head 4,916 + tail 5,084 = exactly 10,000,
six times out of six. The six samples were near-identical content, so retained tokens
and retained bytes moved together and could not be told apart — and nothing asked
whether two proportional measures were being confounded. **Paul asked.** The lesson is
not "check harder"; it is that a bound inferred from samples of ONE payload shape is
inferred from one sample.

**A card can carry a `Verify:` line that is not a command.** `Verify: none` passed
card review, `ready`, and spawn, and failed only at `_record_round`, where the shell
returns 127 and the refusal blames PATH. `verify_refusal` checks that the label has
text after it and nothing checks that the text is runnable. It cost a re-mint, a
re-run plan review and a full re-review.

**`Files:` lines are frozen at `ready` while the work is still discovering its
scope.** Three of five cards shipped diffs their own Files line contradicts, and land
refused twice on `docs/DESIGN.md`. Sprint open reasons about lane collisions FROM
those lines, so a wrong line is a wrong lane plan — and the lead cannot amend one
without re-minting through a plan review.

**The lead's own invocation was outside every gate.** I piped `close.py` into `tail`
in a background shell. A pipe reports tail's exit status, so two review rounds died
mid-commit reading as "exit code 0", and I filed a note blaming the pipeline before
proving it was mine (75842bb4, corrected by de7bc1aa). Nothing in the process says a
leg must not be piped, because until a lead did it nothing needed to.

## 3. What earned its place, and what cost more than it returned

**Earned: the falsifier batch as a gate, not a report.** It refused the close four
times — a stale record, another stale record, a fixture broken by a new wall stanza,
and a wall-clock test — and every refusal named a real defect in the tree.

**Cost more than it returned: "file-disjoint means parallel lanes."** Third sprint
running. The sprint-009 card asserted the cards shared no path; all five edit
`docs/DESIGN.md`, because that is where a card records its decision. Sprint 8's retro
killed this premise for GATES; this sprint shows it was never true for FILES either.

**Cost more than it returned: a 10-second poll bound.**
`test_spawn_escalation.py` polled 1000 × 10ms for a subprocess to file a record.
Nothing there asserts speed. Under `-n auto` with ~900 siblings it took story-061's
land and then the sprint close, green in isolation in 1.04s both times.

## 4. The proposed diff

- **`.xp/constraints.md` #16, funded by shrinking #9.** New: *a bound in wall-clock
  seconds measures the machine, not the code — a test's timeout is a HANG GUARD, so
  make it generous or assert the event instead.* Four gate failures this sprint and
  three the sprint before. It is funded rather than added: #9 currently restates the
  comment rubric that `PROCESS.md` also carries and injects every session — one rule,
  two implementations — so #9 keeps its unique half (the 20% budget, and why a comment
  rots silently) and points at the rubric instead of copying it. constraints.md is at
  4,432 of its new 4,500-char wall, so this is a displacement by arithmetic, not by
  preference.
- **`CLAUDE.md`: never pipe a close leg.** Repo-local, not shipped: a pipe reports the
  pipe's exit status and buffers the leg's last line. It cost two rounds today.
- **`.xp/system.md`: `docs/DESIGN.md` is shared by every card by construction**, so
  lane reasoning at sprint open must exclude it rather than re-derive the claim each
  sprint and be wrong.

## 5. What carries

Sprint 10 candidates, all recorded with evidence: no verb reopens a FINISHED story
(984a07f3); salvage blames a human for HEAD motion `close.apply_patch` caused
(75842bb4); land should REPORT an uncovered merge delta rather than refuse it, Paul's
proposal, with the sprint-review bundle carrying the list; a `Files:` amend verb, or
Files as a declaration land reports; story-051's dispositions; and a free-review lens,
which Paul ranked low and which must be project-neutral — our release constraints are
not a consuming project's.
