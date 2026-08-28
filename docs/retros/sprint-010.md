# Sprint 10 retro — commands are argv, handbacks are states

Two scheduled stories landed: 062 replaced shell execution of `Verify:` with one
argv-command-list grammar; 063 made FINISHED a first-class handback state. The close
also fixed two release blockers found by the falsifier batch. The release is v0.11.0.

## 1. What the process caught

**The story reviewer made the state model earn its name.** Story-063 round 1 exposed
that a killed successor could inherit a stale FINISHED credential. The lead fixed
launch to write RUNNING; the confirming reviewer then found the repair text still
offered hand-writing FINISHED. Round 2 enumerated NEVER SPAWNED, RUNNING, STOPPED and
FINISHED, walked the STOPPED recovery, and left 950 tests green.

**The falsifier batch stopped the release five times for three kinds of drift.** The
fast tier crossed its 120-second usability guard; two records named tests Story-062
had moved or strengthened; two inline falsifiers still passed shell strings into the
new argv API; and shipped `session_start.py` comments cited this project's constraint
15, which resolves to nothing in a fresh consumer. Each refusal was actionable. The
final corpus and full tier passed, 950 tests.

**Moved-trunk land checked the integration we will ship.** Paul's finder/fixer role
change moved `sprint-010` after Story-063's review. Land trial-merged the reviewed
story with that config and ran its full tier before accepting it.

## 2. What it missed

**Story-close did not migrate the records whose executable subjects Story-062
moved.** The behavior was reviewed and green, but the durable ledger still named the
old node and old argument shape. This is exactly why resolved records keep running;
the miss is timing, not silence. Sprint close found it, after several costly restarts.

**`-n auto` was slower than half the workers.** On this 16-logical-core machine,
auto took 135–253 seconds for the fast tier. Eight workers ran 934 tests in 92–110
seconds. The full 950-test tier at `-n auto` took 164 seconds. Worker count is a
contention choice, not a synonym for maximum throughput.

**Thirty-eight notes reached this close undisposed.** Many had already shipped in
Stories 053, 055, 060, 062 or 063; correction pairs and low-priority observations
still remained live beside them. Sprint close listed all of them and forced the
ledger back to zero. Three executable decisions became cards 066–068; none remains
owned only by a note.

## 3. What earned its place, and what cost more than it returned

**Earned: exact falsifiers on resolved records.** A renamed node exited 4 instead of
quietly matching nothing, an obsolete API construction red instead of certifying a
warning, and the consumer-scaffold citation walk found the local index leak. The
batch was expensive because it was independent pressure, not because it was busywork.

**Cost more than it returned: automatic xdist fan-out in the commit wall.** Sixteen
workers oversubscribed subprocess-heavy fixtures and made the supposedly fast tier
both slower and noisy. The project fast tier, hook and its cost falsifier now agree on
eight workers; the 120-second and 150ms/test bounds did not move.

## 4. The proposed diff

- **`.xp/config.yml`: diversify the sprint review.** Finder and fixer use
  `codex/gpt-5.6-sol/high`; verifier and closer remain `claude/opus/high`. This is
  Paul's explicit choice and this sprint review will walk the mixed pairing.
- **`.xp/config.yml`, `lefthook.yml`, cost falsifier: cap the fast tier at eight
  workers.** Measured green at 934 tests; no consumer template changes.
- **No constraint or system rule added.** Existing constraints 2, 3, 11 and 15
  already decided every blocker. Adding prose would duplicate rules that worked.
- **Plan cards 066–068:** clean merge deltas go to sprint review; free land uses the
  story tier; ready cards gain a reasoned Files amendment and credential re-mint.

## 5. What carries

Nothing remains only in the note ledger. Stories 066–068 are explicit unscheduled
cards. GitHub cards 064 and 065 remain unscheduled for the card-review contradictions
recorded on Sprint 10's own card; no implementer is asked to decide them under load.
