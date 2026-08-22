# Plan slice under review — three candidate stories

Review these three story cards as a plan reviewer would: the sprint they belong
to has a cap of 6 and currently holds three other stories. The project is a
lightweight XP process plugin for coding agents; its constraints and system
context are in the files handed to you alongside this one.

#### story-013 — constraints promotion with caps   [ready]
Context: CUT from story-009 at its plan review — a work.py subcommand sharing
nothing with sprint_close.py but a call site, and the only piece of the sprint
close whose absence does not block one (a human hand-edits constraints.md at the
retro, which is what sprint-001 did). Depends on story-009's record ids.
Also carries the OTHER half of note 7df6b116, the half that belongs to work.py:
resolve() checks only that the replacement falsifier is GREEN, never that it is
COUPLED to the claim, while its docstring and PROCESS.md both promise "a wrong
resolution reds later and the record reopens" — true only under coupling.
Files: plugins/xp-plugin/scripts/work.py, tests/test_work.py
AC:
- Given a constraint is promoted, Then the append path enforces a per-item AND total char cap and REFUSES over it — constraints_cap counts line-items, not size (10 items = 2,090 chars here), and the predecessor's json bounded size by validating at write, not by being json
- Given any size refusal, Then the message names the cap, the current value, and the next ACTION (which item to retire), and the line that blew is the line that reds — story-007's budget test sent the reader to trim TEAMMATE.md for a defect that was a new agent
- Given a resolve, Then the resolved record's Claim and its ORIGINAL falsifier are echoed to stderr BEFORE the append, so the substitution is legible at the moment it is made (measured: two of three resolutions filed at the last sprint close did not cover their claims, both written by a lead who wanted the batch green)
Verify: pytest -q tests/test_work.py
Close review: standard
Executor: (default)

#### story-015 — the record lifecycle cannot wedge   [ready]
Context: THREE WEDGES, all found by RUNNING the last sprint close rather than by
reading it, all consequences of deriving record ids from content — which remains
the right call for an append-only file (an ISO second is not a name; 48 concurrent
appends share one). What is missing is a stated escape hatch for each.
(a) Archived falsifiers get synthetic `archive:N` ids that `resolve` can never
match, so a red archived falsifier wedges the sprint close until archive.md is
hand-edited. DESIGN §4 permits the archive to purge; nothing states or implements it.
(b) Two records with identical bodies filed in the same second share an id, and
the ambiguity rule then refuses both FOREVER — a permanent wedge, not a typo message.
(c) A bug whose FIX IS THE RELEASE blocks the release: one record's falsifier could
not green until the PR merged, `sprint start` refused, and the only exits were to
falsify a resolution (what constraint 11 forbids) or to proceed past a red batch.
The lead proceeded, on the record, deliberately. The answer is NOT a skip flag —
that is the silence-a-live-bug hole — but a record that NAMES the release it waits
on and is re-checked at the next sprint start.
Must land before this sprint's own close leg runs; (c) is the one that has already bitten.
Files: plugins/xp-plugin/scripts/work.py, plugins/xp-plugin/scripts/sprint_close.py,
tests/test_work.py, tests/test_sprint_close.py, plugins/xp-plugin/PROCESS.md
AC:
- Given a RED archived falsifier, When the batch runs, Then the refusal names a resolvable id and an executable next action, and re-running after that action proceeds — fault-inject: a fixture archive.md with a red falsifier must wedge the CURRENT code and pass the new one
- Given two records with byte-identical bodies filed in the same second, When either is resolved, Then the CLI disambiguates them (never "refuses both forever") — fault-inject by constructing the collision, not by asserting an id format
- Given a bug marked as waiting on a named release, When sprint start runs, Then its falsifier is REPORTED-not-fatal for that release only, and at the NEXT sprint start it is fatal again with no further marking possible — the record states what it waits on; nothing offers a skip
- Given the batch, Then every cheap falsifier runs BEFORE the full tier — the last close spent 256 tests (~25s) to refuse on a grep
- Given PROCESS.md's record lifecycle section, Then it carries the archive purge rule and the waits-on-release state, asserted as a red test, not as a coherence pin
Verify: pytest -q tests/test_work.py tests/test_sprint_close.py
Close review: deep
Executor: (default)

#### story-010 — size-ratchet   [ready]
Context: DESIGN §9's budgets become a command. FIRST, not last: the close
component measures 1,041 of 1,100 today (close.py 490 + review.py 218 +
bookkeep.py 129 + sprint_close.py 204) and story-014 spends into that headroom —
the wall goes up before the spend, not as a post-hoc verdict on a merged story.
NO GITHUB ACTION, cut at plan review: it is a second copy of a gate pre-push
already runs, on a surface system.md declares no harness for, and it cannot be
executed before it merges (constraint 12, which has bitten twice). The only hole
it would cover is `--no-verify`, which CLAUDE.md already calls a values violation.
ONE COPY OF THE NUMBERS: ratchet.py holds the sub-allocation and DESIGN §9 keeps
the total, the rationale, the only-ever-lowers rule and the sacrificial-feature
order. Closes bug c2d7ffdf — but its falsifier asserts the digits are PRESENT in
CLAUDE.md and .xp/system.md, so deleting them REDS it: this story must `work.py
resolve` it with a replacement covering the stronger claim, or it wedges the
sprint's own close (found at plan review; it was a trap of my own making).
Size: ratchet.py lands in misc, measured 366 of 900.
Files: plugins/xp-plugin/scripts/ratchet.py, lefthook.yml, tests/test_ratchet.py,
CLAUDE.md, .xp/system.md, docs/DESIGN.md
AC:
- Given the repo within budgets, When ratchet.py runs, Then exit 0 printing the per-component MEASURED/cap table — a live number on every push, because the sprint-002 SIZE BREACH was an agent estimating against a stale one and a pointer does not fix that
- Given a fixture tree constructed OVER a budget, Then nonzero naming the budget and the overage (the guard fault-injected, constraint 2)
- Given a FIXTURE tree whose comments + docstrings exceed 20% of its Python lines, Then nonzero naming the density and the worst file — a fixture, not this repo, which sits near 17% and would green a do-nothing implementation
- Given the sub-budgets, Then a test asserts they sum to ≤ the total, so raising one requires lowering another — constraint 1's displacement rule made mechanical rather than promised
- Given lefthook.yml, Then pre-push runs ratchet.py (structural pin)
- Given CLAUDE.md and .xp/system.md, Then neither states a budget NUMBER (the falsifier matches the budget shape — `≤N lines/words` against a component name — not any digit: system.md:7 says "Python 3.11+"); both point at the command, CLAUDE.md's "DESIGN is the authority" line gains the budget clause, and c2d7ffdf is resolved with a replacement that reds if a number comes back
Verify: pytest -q tests/test_ratchet.py
Close review: standard
Executor: (default)
