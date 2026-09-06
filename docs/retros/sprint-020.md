# Sprint 20 retro — "What we ship says what it does"

Five cards, all landed: 095 (secrets wall), 120 (extraction), 112 (review authority),
113 (free start on trunk), 119 (mid-sprint options + profile target). Milestone 10 is a
completion candidate. Full tier at close: 1,409 passed in 283.67s.

## 1. What the process CAUGHT that we would otherwise have shipped

Name the mechanism, not the finding — and this sprint the same mechanism fired five times.

**The story-reviewer's fourth stage caught a red full tier on three separate cards**
(095, 112, 113), each time on failures the CARD'S OWN Verify never named. story-112's was
the sharpest: `close_helpers.worktree_land_setup` runs `close review` in a repo with no
.xp/system.md, which 112's new policy refuses, so a test died in its fixture. Neither the
card's Verify nor the fast tier reaches it — only the push gate would have, after land.

**Fault injection caught two guards that could not red against their own subject.**
story-112's unreadable-rubric tests constructed UNREADABLE as a directory only, so narrowing
`except OSError` to `except IsADirectoryError` left all 24 parametrised cases green while the
permission-denied state the AC names still raised a traceback. And story-095's calibration
test — the one that exists to prove the secret fixtures are not vacuous — was ITSELF ~5%
vacuous: 16 of 300 draws of its AKIA+hex fixture did not red at gitleaks 8.30.1.

**The slate review falsified an AC that could not be satisfied.** story-095's AC2 told a
pusher to remove the secret and retry; walked, that is rc=1 STILL RED, because the
introducing commit stays inside `remote_sha..local_sha` forever and only a history rewrite
greens a range scan. We would have shipped a refusal naming an action that does not work.

**An executor refused a self-contradictory plan rather than working around it** (story-120),
leaving a clean worktree and a verified baseline instead of a half-done extraction.

## 2. What it MISSED, and which mechanism should have caught it

**The lead's walk missed what the reviewer found.** I walked story-095's merge wall on a
FRESH scaffold with fault-injected controls on both variants — correct, and it proved the
shipped fix. The reviewer walked the SYNC path and found the wall erases itself: lefthook's
auto-install rewrites .git/hooks/pre-push on any lefthook.yml checksum change. A walk proves
the path you take and says nothing about the path you did not. The mechanism that should
have caught it is the walk's own scope statement: walks/story-095-secret-wall.md now names
what it did NOT walk, and that section is the one worth keeping.

**Nothing guards tests/slow_tests.json.** 24 of its ids name tests pytest no longer
collects, and THREE of those arrived during this sprint from 113/119's own work. story-120
correctly re-pointed 22, but new drift landed immediately behind it because
check_falsifier_node_ids.py reads work.md falsifiers only. Those tests now run in the fast
tier at every commit with nothing reporting it. A sibling guard over slow_tests.json is the
missing mechanism (note 80b56970).

**The batch aborted the close on a fixture that had broken the same way before.**
falsifier_hookspath_bypass.py hand-lists the helpers our lefthook.yml sources; 095 added a
third and pre-push exited 127, so the falsifier refused instead of measuring. Its own comment
records the identical break at sprint-015 close. Fixed sprint-direct at d5daf2b by DERIVING
the list from lefthook.yml. Twice for one reason means the mechanism was wrong, not the
maintenance.

## 3. Which rule earned its place, and which cost more than it returned

**EARNED: constraint 12's "prose that instructs an agent to run something is such a path."**
It is why story-095's impossible remediation was walked rather than reasoned about, and the
shipped refusal now names the rewrite that actually greens the scan.

**EARNED: the mandatory card refresh before mint.** Every one of the four refreshes changed
its card. story-119's corrected ELEVEN claims, including one that was wrong when I wrote it
at slate review, not drift. `spawn.py ready` refusing without a refresh is what forced it.

**COST MORE THAN IT RETURNED: nothing was retired this sprint, and that is the honest
answer.** No rule misfired. The candidate for displacement is proposed below rather than
taken, because retiring a constraint is a "different project" decision and it is Paul's.

## 4. The proposed diff — FOR PAUL, none of this is applied

**(a) A new constraint, which must displace one (note d2d1506e).**
  A REFUSAL'S NAMED REMEDY MUST BE COMPUTED FROM THE SAME STATE ITS TRIGGER TESTED; a remedy
  drawn from broader state can be followed exactly and leave the trigger unchanged.
  Test shape: perform the named remedy, re-run the check, assert the trigger is now false.
  This is NOT constraint 15 — 219a3598's profile note has one unambiguous trigger and no
  state conflation, yet names a contributor that cannot silence it. Constraint 15 DOES cover
  841d3e6e, which is why that one needs no rule. Evidence: one clean instance plus one
  variant, in one sprint — thin for a slot. Recommend RECORDING, not promoting, until a
  third sighting.

**(b) `free work slotless` no longer appears anywhere in the shipped plugin** (note
  219a3598). PROCESS.md was its only home and story-119 displaced it to buy the mid-sprint
  prose. Both sentences serve the same reader — a lead deciding what to do with work found
  mid-sprint — so this may be the wrong trade. Reversible by displacing something else.

**(c) Two live notes have no home and will be lost.** 45c848a4 (the six-states-one-message
  defect in `_run_refresh`; its named destination story-107 is [planned] and its card does
  not mention it) and e49742d5 (existing lefthook consumers never receive the new
  pre-merge-commit until they resync — no card, no debt, no printed message, on a
  security-relevant hook). Both want a card or a debt record, not another sprint as notes.

**(d) Three of four ratchet components are over guideline** — close 2,986/2,598, spawn
  1,561/1,558, misc 1,539/1,489 — and every reviewer this sprint reported that most of the
  overage predates its card. The table reports and the 500-line file cap refuses, so nothing
  is blocked; but "advisory number nobody acts on" is the shape this repo distrusts, and it
  has now been carried across three sprints. Either re-cut the guidelines against measured
  reality or say plainly that the component table is informational and the file cap is the
  only wall.
