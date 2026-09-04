# Sprint 18 retro — the numbers left; the reviewers kept working

Five cards landed. The shipped Python is 6,309 lines against the predecessor's
roughly 52,500: an 88.0% reduction. Removing component and density refusals did
not reverse the size cut. The close component is 2,620 against its former 2,598
guideline; the report made that growth visible without turning arithmetic into a
design decision. The 500-line file wall stayed hard.

## 1. What the process caught

**Card refresh caught premise rot before every affected executor.** It removed
obsolete cap files from story-110, added a test that the card itself predicted
would red, corrected moved code citations, and distinguished a live profile
measurement from a constant. Stories 105 and 094 also needed repeated refreshes
because their first rewrites still contradicted their own Files declarations.
The value was not fresh prose; it was refusing to mint a digest for stale prose.

**Execution-plan review found omissions that a diff review would inherit.** On
story-110 it added the only executable check for retiring the `session_start`
banner and stopped historical fixture prose from being rewritten into a false
claim. The plan changed before code, where the correction was cheapest.

**Diff review kept finding defects after the numeric gates were gone.** Story-094
needed two rounds: the first caught recovery advice that could destroy
uninspected work, and the second caught dirty-and-moved salvage saying “read”
before offering a reset. Story-110's reviewer fault-injected a new registration
test and proved it greened while the forbidden executor charter was present.
These are the defects the sprint thesis said independent readers find; the
component totals found none of them.

**The sprint falsifier batch caught one cross-story release defect.** A shipped
comment cited this repository's constraint 15, which a fresh consumer does not
have. The exact falsifier redded at close, the stable rule name replaced the
project-local index in `ac93c78`, and the replacement now greens.

## 2. What it missed

**Note lifecycle had not finished for 43 records from Sprints 15–17.** The close
mechanism surfaced them, but previous human closes left already-carded,
superseded and deliberately loud observations open. That made this close re-read
decisions it could not improve. This close archives every one after classifying
it; no note carries merely because it once cost effort to write.

**A historical design row still names `TEAMMATE.md`.** Story-110 deliberately
kept docs history outside its rename, and the reviewer made the residual loud.
It cannot corrupt execution: the shipped tree, system context and tests all name
`EXECUTOR.md`. It is archived as bounded documentation drift, not promoted into
another always-on rule.

**No automated mechanism should decide the prose-success criterion.** The
executor brief's declarative rewrite was intentionally reviewed by reading it;
a token blacklist would reward euphemism and certify the wrong property. The
review found concrete mechanism and test defects around it instead.

## 3. Which rule earned its place, and which cost more than it returned

**Earned: fault-inject every guard.** It exposed the vacuous role-registration
assertion, both dangerous salvage paths, and the close-time constraint citation.
The pattern held across prose, recovery and code.

**Cost more than it returned: component and density refusal thresholds.** The
v0.18.1 close spent three rounds and four cap raises on arithmetic while every
real defect came from a reviewer. Story-109 removed those refusals and kept the
measurement-integrity checks, report, and 500-line structural wall. This sprint
then completed with reviewers still finding substantive problems and with the
88.0% size reduction intact.

## 4. The proposed diff

1. **Done — `tests/scripts/ratchet.py` and its tests:** component and density
   ceilings became reported guidance; empty measurements and files over 500
   lines still refuse.
2. **Done — spawn and close surfaces:** durable artifact handoff, distinct stage
   logs, artifact-first salvage, and separate planner/executor briefs remove work
   from the repeated and recovery paths.
3. **Done at close — `plugins/xp-plugin/scripts/review.py`:** replace the shipped
   numeric constraint citation with the stable name “distinct-state rule”.
4. **No new constraint:** the note that an agent must not be launched merely to
   flip a bit is already constraint 3's “independent adversarial pressure, not
   bookkeeping”. Repeating it would recreate the prose duplication this sprint
   removed.
