# Changelog

Release notes started at v0.6.0; earlier entries are summarized from their
tag and merge messages. Full detail lives in the merge history and the
per-sprint review reports.

## v0.23.12 — a story lands only the files its card declares

GitHub #86. Nothing at story close compared the paths a story changed with its card's
`Files:` line, so an executor's undeclared files merged, and the Verify gates those
files trip never ran. Story and free land now refuse BEFORE any merge, push or PR when
the story's changes, from its merge-base to HEAD, add, modify or delete a path its
Files line does not name. The refusal lists every such path and the amend command, and
`--dry-run` prints the same refusal. The base is the one land already uses: trunk for
free work, the integration branch for a carded story. So trunk motion and sibling
stories merged into a sprint branch are never counted as this story's. The one
exemption is a free release's `version_files` manifests, since post-merge checks those
against the version. A changelog and every other release artifact must be declared.
Files entries are exact paths, with no directory or glob form.

## v0.23.11 — a record is resolved by the lead at close, on the landed tree

GitHub #89. The only resolve guidance any role received was JUDGMENT.md's "resolve —
substitutes a green falsifier", and every executor is handed JUDGMENT.md. So executors
resolved debts on their own judgment, before land, sometimes on falsifiers their card or
plan review had ruled out. Parallel lanes then went red on each other's node ids through
the shared ledger. The bullet now reads "lead only, at close, on landed tree". Prose
only: `work.py resolve` does not refuse by role, and land does not check which
falsifier a resolve used.

## v0.23.10 — the depth a plan review assigns is the depth the story is reviewed at

GitHub #87. The plan reviewer owns a story's close-review depth and writes
`Close review:` into the execution plan. The story reviewer weights its checks by that
depth, but its prompt carried only the plan.md card, so a raise to `deep` was recorded
and the review ran at the card's depth. The review prompt now carries a
`Close-review depth` section with the effective depth and who assigned it. That is the
deeper of the card and the reviewed plan, since a plan review can raise the depth but
never lower it. A plan draft that exists but cannot be read reviews `deep` and says so.
A story with no plan review uses the card's depth. The card is not rewritten, so its
minted digest, resume and land are unchanged.

## v0.23.9 — a sprint named 2b-11 opens, releases and reads back as released

GitHub #88. `close.py sprint` and `slate_review.py` took a sprint id as a string, but session start and the release record read it through `int()`. A
project naming its sprints like `2b-11` got `NEXT: recovery required — recorded branch
sprint-2b-11 is not named sprint-N` at every SessionStart. Its post-merge created the
tag, crashed writing the release record, and then refused to re-run because the tag
already existed. Session start now selects the heading whose id derives the recorded
branch, using the same rule close.py opens it by. With no branch recorded, a plan with
any non-numeric heading falls back to its last sprint heading, and the provenance line
says which rule chose. A release record is keyed by the id, so records for numeric
sprints are unchanged. Post-merge refuses an id that is not one safe path segment before
tagging, and removes the tag when the record write fails for any reason, so a failed
post-merge stays re-runnable.

## v0.23.8 — an amended card is re-planned before an executor runs on it

Bug f80395a2. `spawn.py amend` rewrote only the card credential, and resume
re-ran the planner and the execution plan review only when that review had
BLOCKED, so a card amended after a plan review that ran resumed straight to an
executor holding a plan reviewed against the old card. The executor stopped on
the contradiction, and amend-then-resume could not finish without the lead
steering the plan by hand. The handoff now records the card digest its plan
review approved; a resume whose current card differs re-runs the planner and the
plan review first. An unamended resume, a blocked review, a single-file story and
an amend before the first spawn behave as before. Walked with sonnet and codex
planners; a haiku planner may treat the old reviewed draft as work to do, which
the existing "the planner changed the repository" stop still catches.

## v0.23.7 — a reviewer is handed the diff's address, not its body

Every review prompt pasted the whole diff in: once for a story or free review, and
once per stage of a sprint review — three finders, up to two verifiers, the fixer
and the closer — so a sprint-sized diff could fill most of a smaller model's
context window before the reviewer read a file. A review prompt now names the
range instead: full base and head SHAs, the `git diff` command that reads it and
its per-path form, the commit list, and per-file change counts. An empty range
says so. The reviewer reads as much of the diff as its job needs; section titles
are unchanged.

## v0.23.6 — a released sprint is not a sprint waiting to close

SessionStart told a lead to run `/sprint-close` on a sprint it had already
released, at every session until a new sprint existed, because nothing recorded
that the sprint shipped. Sprint post-merge now writes a release record under the
data root naming the sprint, its merged sha and its tag, or no tag under
`versioning: off`; a dry run or a refused post-merge writes none. NEXT reads it:
a released sprint with nothing open says to run `/create-sprint`, a released
sprint with an open card names the card to schedule into a new sprint, and an
unreadable record asks for recovery. A sprint with no record behaves as before.

## v0.23.5 — a headless role finishes its work inside its turn

Issue #80. A headless run ends with its turn and kills any background task, and
Claude Code moves a foreground Bash command into the background once it outlives
its timeout, so a reviewer could exit with a staged, unverified patch and no
round. Every headless Claude role now launches with
`CLAUDE_CODE_DISABLE_BACKGROUND_TASKS=1` and its Bash timeouts at the role's
bound, so long commands run to completion in the foreground. Values already set
in the launching environment are kept; Codex launches are unchanged. The bound
now defaults to four hours for executors and reviewers alike, and
`XP_AGENT_TIMEOUT` still overrides it.

A background task still killed at exit is named in the run's error output. A
review refusal over a dirty tree saves the staged and unstaged work as a patch
under the data root's `reports/` before offering `git reset --hard`, and offers
no destructive recovery when it cannot save one.

## v0.23.4 — versioning can be turned off

Issue #77. `versioning: off` in `.xp/config.yml` turns off the plugin's
versioning for a project whose releases and versions belong to another process.
Sprint land and free land compute no version, so a repository whose tags follow
another scheme is no longer refused, and their PR titles name the sprint branch
or the free slug. Sprint post-merge cuts no tag, still runs the sprint-close
lifecycle and clears the recorded sprint branch; free post-merge cuts no tag and
still finishes the card. `version_files` is ignored in this mode, and any other
value of `versioning` refuses. Unset keeps today's behaviour. PROCESS.md and the
close skills no longer describe tagging, which the scripts report.

## v0.23.3 — bracketed paths are paths

Issue #81. Files declarations now preserve path segments containing parentheses,
square brackets, or braces while continuing to refuse whitespace outside a
trailing annotation, and refuse unbalanced brackets such as `test_{a,b}.py`
shorthand. A parenthesized segment is no longer silently truncated, and `x.py(note)`
without a space now declares that literal path. The refresh receipt tracks a
bracketed path literally rather than as a git glob.

When a card refresh refuses a Files declaration, its terminal now names the bad
entry and repair instead of reporting a missing receipt and asking the lead to
repeat the same failing refresh.

## v0.23.2 — a resume refusal names a route that can succeed

Issue #78. When `spawn.py resume` refused a taken-over tree, its recovery said
only "commit, then resume". A lead who committed a complete story by hand
was then refused with "the teammate made no commits of its own" and given the
same advice, so following it looped forever at the cost of a full teammate run
per lap. Both resumed refusals now name both routes: if the committed work
completes the card, run `close.py story <id> review` (or `close.py free <slug>
review`) from that worktree; if work remains, resume. The no-commits guard is
unchanged.

## v0.23.1 — absence is not a pass

Release post-merge now refuses before tagging when `version_files` is unset or
empty, and names the `.xp/config.yml` key to configure. A configured matching
manifest still cuts the tag unchanged. A project whose version does not live in
a JSON manifest sets `version_files: none` to release without that wall; the
tag line then says no manifest was checked.

The seven close actions that parsed and then dropped `--dry-run` now preserve
their branch, review artifacts, plan, sprint record, release tag, and teardown
state during previews.

Land no longer charges another review merely because trunk moved. It permits a
trustworthy forward base change when trunk and the story touched disjoint files,
while shared paths and divergent recorded bases still refuse.

## v0.23.0 — nothing breaks a consuming project in silence

Milestone 12. Five defects that a consuming project would have hit without being
told, and one that would have cost it a rule.

The SessionStart banner names the plugin's absolute path once instead of twice,
which halves the profile's cost per path character and raises the derived
constraints allowance to 4,576 bytes — a project whose `.xp/constraints.md` sits
at the shipped 4,500-character cap now has it delivered whole, where before it
lost a rule at a long checkout path.

`close.py sprint <id> milestone-done --dry-run` no longer performs the close it
previews. The flag was parsed and dropped, so a preview closed the milestone and
the real run that followed refused as already-done.

A relaunched review no longer destroys the artifacts `salvage` exists to record.
Unrecorded reports and patches are rotated aside rather than unlinked, on both
the story and sprint paths, and a round recorded out of order can neither clear
a live blocking finding nor be cleared by one that never saw it.

A `Worktree bootstrap` declaration written as a markdown heading is now refused
loudly, naming the offending line and the one-line shape that works. It used to
be skipped in silence, byte-identical to having no bootstrap at all, which left
a spawned executor in a worktree with no dependencies installed and nothing said.

`SessionStart` now warns before truncation when a project's constraints exceed
the derived budget, naming the overage and the remedy. The git-hook wall is
unchanged: a project between the two limits still commits.

## v0.22.1 — the running plugin owns its pin

After an upgraded plugin is reloaded in an existing lead session, its next Stop
hook now repoints `env.json` to the root and version of the copy actually
running. Spawned roles cannot move the lead's pin, an already-current pair is
left byte-untouched, and a failed repoint cannot disable the existing red-Verify
gate. The recovery refusal now names both truthful routes: a new lead
SessionStart or `/reload-plugins` followed by the next turn.

## v0.22.0 — the close spends what it must and keeps what it knows

The sprint close paid twice for what it already measured, and threw away what it
already knew. Six cards, all of it observable in this release's own close.

The falsifier batch stopped re-running records the ledger already calls disposed,
and a record tagged with a cheaper tier now defers when a tier that covers it is
about to run — declared by the project, pinned to the tier commands it was declared
against, so a tier edited later refuses loudly instead of silently un-covering every
record tagged with it. Before this, only the literal `full` bought the deferral, so
the honest tag was the expensive one and almost nobody used the field.

The full tier runs once per close when the tree has not moved, keyed on the staged
merge's tree rather than a commit SHA — on the pending arm the tree being measured
has no SHA at all. The release PR now carries the sprint's record: each story with
its merge SHA, the round's counts, the tier that ran and the tree it covered, and
whether that tier ran in this leg or reused a receipt.

`recover` describes the sprint the state root records as OPEN rather than the
highest-numbered heading, falling back loudly. A spawned session no longer repoints
the lead's pinned plugin root, and a lead's refresh is reported rather than silent.

Also fixed: a work.md record's `Files:` line is parsed by the same rule as a card's;
the sprint marker survives a concurrent write landing during a long tier; and a
plugin-root move notice is bounded so it cannot evict a constraint from the profile.

## v0.21.5 — every plan.md writer takes the lock

`work.edit_plan()` does read-modify-write inside an exclusive flock, and
`flip_card` says why: a sibling lane may be flipping its own card right now. But
only two callers used it. `slate_review.py` restored a card with a bare
read-then-write, and the card-refresher subagent edits the plan by shell, detached
for minutes, with nothing about the lock in its charter.

"Different cards cannot collide" holds only among `edit_plan` callers. An unlocked
writer rewrites the whole file from whatever it read, so a `ready` that flipped one
card under the lock was erased by a refresher that had read a different card
minutes earlier — no error on either side, and the ready marker left disagreeing
with the plan.

Reported from a consuming project (#69), which also narrowed it correctly: `ready`
and `land` interleave fine, so the lock was not widened. Only the unlocked writers
changed.

This is the code cause of a rule this project had been paying in prose — "never
write plan.md while a refresh is running" — which constraint 5 says belongs in the
code rather than in a lead's memory.

One guard changed direction alongside it: a refresh that also moves text outside
its own card no longer refuses. Under the candidate handoff that motion cannot be
told apart from a sibling lane's own locked flip, and refusing it would red the
parallel case this release exists to make safe. It is reported on the receipt and
in the handoff line instead, and `ready` proceeds.

## v0.21.4 — a declared path is never silently un-declared

`declared_files()` split the `Files:` block on commas before normalising each
entry, so a parenthetical annotation containing a comma was split across it and
the real path it annotated never entered the declared set — replaced by two
fragments that match nothing.

It mattered because writer and reader shared the break: the card-refresh receipt
was built from `declared_files()` and checked with the same call, so the check
compared a broken set against itself and could never refuse over a dropped path.
The fragments stored as null and compared equal forever, so a receipt read fuller
than its real coverage. Field-reported (#68) with a card whose central deliverable
was exactly the swallowed files, reported fully checked and never hashed.

The mirror of #45 in the same function: that was a loud false refusal, this a
silent false clearance. Fixed on both sides — an entry that does not resolve to a
plausible path is now reported rather than dropped, and `templates/plan.md` states
the contract it never stated, which is what invited the annotation.

## v0.21.3 — a failed merge says which failure, and the refusal survives it

- **A merge that fails no longer crashes instead of refusing.** Both checkouts in
  `close.py story <id> land`'s local merge path ran under the default `check=True`.
  The recovery one exited 128 whenever a story worktree still held the branch — the
  normal arrangement at land time — so the refusal it was about to print never ran
  and the operator got a `CalledProcessError` naming a checkout instead. The forward
  one is reached only when no separate worktree holds trunk — what a consuming project
  without one always has — and it crashed the same way whenever that checkout itself
  failed, which is how the reported stale lock surfaced there. Neither is attempted
  where a worktree already holds the branch, and a checkout that does fail is now
  reported.
- **A merge failure says which failure it was.** The refusal asserted "merge
  conflict: resolve on the story branch" for every cause, and git's stderr was
  captured and dropped. The reported case was a stale `.git/index.lock` from an
  interrupted land — `fatal: Unable to write index.` — sent to conflict resolution,
  the one remedy that could not fix it. Unmerged paths are now probed before the
  abort clears them; a real conflict keeps its guidance and everything else carries
  git's own reason plus the next action — nothing merged, so clearing the cause and
  re-running land owes no re-review (GitHub #65).

## v0.21.2 — a verdict the harness cannot read is not a rejected plan

- **A plan review is no longer lost to how its verdict was written.** A disposition
  written as a bare JSON object inside prose was found by the parser's own scan and
  then refused anyway — the scan collected it and never used it — with the same
  message as a file carrying no verdict at all. The charter now names one
  unambiguous format, the parser accepts what the charter instructs, and a verdict
  returned by the reviewer but absent from the file is still consumed.
- **A verdict the harness could not read is distinguished from a plan the reviewer
  rejected.** `replan` treated both as "blocked", so `spawn.py resume` discarded a
  clean plan and re-ran planner and reviewer into the same wall — a gate that fails
  closed but is unreachable by retry, at two agent rounds per attempt (GitHub #62).

## v0.21.1 — a passing plan review stops blocking itself over markdown

- **Plan-review reasons are compared by words, not by punctuation.** A reviewer that
  wrote a reason as ordinary markdown in the plan and as plain text in its JSON
  disposition had the whole round discarded (GitHub #60, the sibling of bug
  6677e018 which fixed the blockquote marker the same way). Enumerating markers one
  at a time fixed the blockquote and left the backtick; the comparison now ignores
  presentation as a class, while a reason genuinely absent from the plan — or
  present with different words — still refuses.

## v0.21.0 — what we ship says what it does

Five changes close gaps between what a shipped surface claims and what it does.

- **Every git path runs a secrets wall that can red.** A no-ff merge now hits a
  scaffolded `pre-merge-commit` on both hook variants, and the push arm proves its
  scan range resolves before trusting it — gitleaks exits 0 on a range git cannot
  resolve, so an unfetched remote sha previously published unscanned. The push
  refusal names the remediation that actually works: rewriting outgoing history,
  not a later removal commit. The lefthook push arm is documented as best-effort
  and its skip is pinned by a test, because lefthook's hook sync erases any patch
  we apply to the generated hook.
- **A review refuses without the rubric that defines its judgment.** Story and
  sprint review bundles no longer hand an agent `(missing: JUDGMENT.md)`; missing,
  empty, unreadable and non-UTF-8 are four named states, each with its next action.
- **Free work starts from trunk without moving the lead off it.** `free start`
  leaves the lead on trunk, names where release artifacts get cut, and the review
  path can no longer mint its own credential for work that was never spawned.
- **The teammate profile target is a project's own number.** `profile_target` is
  declared in `.xp/config.yml` (default 806) as a story-card allowance measured
  against each project's floor, replacing a fixed 4,500 that gave different
  projects a 50% different card budget. The note names the plugin's own share when
  the plugin is the largest contributor.
- **The process document names what a lead does mid-sprint.** Record, keep work on
  the sprint branch with `[sprint-direct]`, or cut a patch tag off trunk to ship now.

## v0.20.0 — release evidence stays complete and actionable

Six changes keep release decisions bound to the evidence that actually earned
them.

- **Later review rounds retain every prior finding.** Presentation remains
  bounded in human-facing merge summaries, which point to the exact durable
  round artifact holding the complete result.
- **The full gate can clear only an explicitly bound deterministic blocker.**
  Sprint closers may bind their own blocker to the existing full tier, but code,
  gate or trunk motion and every ordinary judgment blocker still require review.
- **Every review round owns a numbered artifact.** Markers name that artifact;
  missing or corrupt bindings refuse instead of guessing an older report, and
  legacy round-one files migrate without first-gap reuse.
- **Every launched role uses the configuration seat it names.** Planner, slate
  reviewer and card refresher now have explicit routes while older configs keep
  their documented fallbacks.
- **A red falsifier batch preserves the whole diagnosis.** Close reports every
  red command with bounded stdout and stderr and can file one combined bug with
  the stable union of its source Files declarations.
- **Cap-triggered extraction is standing authority.** It needs no separate
  approval; the before/after collection count and green baseline are the
  behavior-preservation wall.

## v0.19.0 — the loop gets cheaper to run and recover

Five changes remove recurring work without weakening the independent feedback
that catches real defects.

- **Component and density caps are guidance, not gates.** The ratchet still
  reports every component, refuses empty measurements, and enforces the hard
  500-line file cap. Shipped Python remains 88.0% smaller than the predecessor.
- **Handoffs carry durable artifact references.** Successors receive paths and
  record ids instead of inlined plans, reviews, and logs; state and rationale
  remain in the prompt.
- **Every story stage has its own transcript name.** Planner, execution-plan
  reviewer, executor, and diff reviewer logs no longer overwrite one another.
- **Salvage protects evidence before diagnosing repository dirt.** Story and
  sprint recovery distinguish absent, unreadable, moved, and dirty states and
  name role-specific repairs without destructive reset advice.
- **Planner and executor receive separate briefs.** The planner gets a resolved
  read-only charter; the executor gets a declarative root brief. The redundant
  close prohibition and manual plan-review affordance are gone.

At close, the falsifier batch caught and fixed one shipped numeric constraint
citation that resolved to no rule in a freshly scaffolded consumer.

## v0.18.1 — the ceilings got a floor, and the prose got its second halves back

A ten-way audit — five skills, five always-on injectibles, each auditor given the
artifact's goal from OUTSIDE it — found ONE defect nine times: the second half of
something squeezed out. Not vagueness, amputation. `free-close` said "your release
artifacts are yours" and never named `post-merge`, which is what tags. Every capped
prose artifact measured 96-100% of its ceiling, and the cheapest words to cut are
the ones supplying a referent, so nine independent squeezes reached for the same
kind of word.

- **Every prose cap carries a floor** — `cap >= live/0.9`, re-cut when a fix lands,
  and the five skill caps are now enumerated from the skills directory rather than
  hand-listed. `xp-setup` joins them: the one skill with no cap was also the only
  one whose defect was a stale claim rather than an amputation.
- **`free-close` names `post-merge`** — `land` opens the PR; `post-merge` tags. A
  lead following the old text shipped an unmerged PR and no tag at all.
- **The loop map names the free lane's entry and its spawn**, and says
  `Background every long leg; no timeout` — a lead who read the old map went from
  `start` straight to `review` and built in their own checkout.
- **`JUDGMENT`'s Bar is a condition on the deviation**, not a second competing rule;
  **`VALUES`' Courage** says fix OR record, now.
- **Five general rules seeded into `templates/constraints.md`**, phrased to carry no
  trace of this repo, with a guard that reds if one does.
- **The byte-profile guard measures its claim, not the machine** — it constructed
  nothing and read whatever path the checkout happened to sit at, so it passed for
  a lead at 59 characters and silently forbade every spawned teammate at 102 from
  committing anything at all.

## v0.18.0 — the default path finishes a multi-file card

Milestone 8's spine. `spawn` runs a story as four staged roles that each do one
thing and exit — planner, execution plan review, executor, diff review — so no
agent waits on a detached child across a turn boundary, which is how the field
report lost 2 of 3 multi-file stories on 0.16.0.

WALKED, not asserted: a real multi-file card, on the scaffold-default
`claude/sonnet/medium`, through all four stages against a live harness
(`walks/story-102-four-stages.md`). Every stage started, completed and exited.
The fourth stage earned its place immediately — it caught the executor shipping
a feature with ZERO executing tests, proven by mutation rather than by reading:
neutering the guard left the card's own Verify reporting the same count the
commit cited.

- **Four artifacts, four names** — every review is now named for what it reads:
  slate review → card refresh → execution plan review → diff review. The sprint
  step's old name, `card review`, moved rather than rotated, so no record filed
  before this release silently inverts.
- **Card refresh** rewrites one card's stale existing-code claims against HEAD
  before `ready` mints its digest, and `ready` REFUSES until it has run. A receipt
  binds it to HEAD and to each declared path's committed state.
- **A blocked plan review can be resumed out of.** It records `blocked` rather
  than nothing, so a resume replans instead of re-reviewing the same draft
  forever — "blocked" and "never ran" no longer spell the same.
- **Land discloses every round's reviewer work**, not just the last. A second
  round used to overwrite the first's coverage, so a lead assented to a merge
  that hid what the first reviewer had changed.
- **An unset test tier is answered identically in both legs** — the git hook and
  the close leg now give the same refusal, discharging a debt filed 2026-08-25
  that asked planning to pick one deliberately.
- **The commit gate got its time back**: the fast tier is partitioned by measured
  duration rather than by hand, taking pre-commit from ~166s to ~58s.

## v0.17.0 — the process runs itself, or it is not a process

Milestone 7 closes. Card review now reaches a lead on **either harness**: a Codex
lead with no `--plugin-dir` and no subagents reaches a real card review through a
headless runner, walked live on codex-cli 0.150.1 — its retries joined the running
reviewer rather than launching a second one, and that review returned RED on the
story that created it.

- **`/create-sprint` and `/free-close`** — the last two loop steps with no shipped
  page now have one, and every command a skill names is walked against the CLI
  rather than pinned as a substring.
- **SessionStart names the next action**, not just state: one deterministic `NEXT:`
  line from card status and worktree state, with every unenumerated state refusing
  to guess rather than inventing a step.
- **A killed review's artifacts outlive the process that wrote it** (issues #41,
  #44): `sprint salvage`, a land refusal that distinguishes "Verify redded on the
  reviewed tree" from "no review ran", and reports that survive the kill.
- **The `.xp/` scope guard reads a `Files:` line as prose** (issue #45): backticks
  and a trailing `(new)` no longer make it refuse a path the card names, and its
  refusal names the patch that survives instead of implying the work is lost.
- **A mandatory step that fails twice escalates** rather than being skipped.

Fixed at close, each caught by the falsifier batch or the sprint review rather than
by a story: the commit gate's ceiling re-cut for a suite grown to 1,129 tests, a
falsifier naming a test another story had moved, two comments citing a constraint
index meaningless outside this repo, and a card-review marker whose writer and
reader disagreed on zero padding — which made an incomplete review indistinguishable
from a completed one, a skill-command walk that covered `/create-sprint` alone while
the other four skills' spellings stayed pinned as substrings, and the seam between
the recovery this release ships and the route a lead is sent down to reach it —
review deletes the round's artifacts before it spawns, on BOTH nouns, so issue
#44's own suggested recovery destroys what `salvage` would have recorded. It now
says what it is about to delete, and names salvage, before it deletes it.

## v0.16.0 — the loop names the thing that carries each step

Sprint 15, opening Milestone 7. v0.15.0 shipped and leads did not follow the process
unless a human named each step; the cause was in the artifacts, not in anyone's
attention. Five cards make the loop self-routing.

- **`JUDGMENT.md` is new, and every injection carries it.** The comment rubric, the
  finding bar, the record shapes, the polarity contract and the red/hooks rules were
  duplicated between `PROCESS.md` and `TEAMMATE.md` and reached the reviewers through
  neither. They now live in one shipped document that all five injection sites carry,
  and `PROCESS.md` more than halves — 2,826 characters to 1,274. The teammate profile
  cap moves 1,200 → 1,365 to fund it, with the measurement and its funding in the
  commit that took it.
- **Every loop step names the command or skill that performs it.** `PROCESS.md`'s five
  steps named no skill at any step and never named `spawn.py <story-id>` at all; the
  skills appeared once, in a sentence *about* them. Each step now routes: `/xp-setup`,
  `spawn.py ready`, `plan_review.py`, `spawn.py <story-id>`, `/story-close`,
  `/sprint-close`, `close.py free`.
- **The guard that checks that routing now acts on real surfaces.** It enumerates the
  shipped skills directory rather than a hand-list, scopes routing to numbered steps or
  to stdout captured from a real leg run, and walks the named commands with `--help`
  instead of matching a hardcoded table that would survive a rename. The no-`.xp/`
  refusal routes to `/xp-setup` rather than to version control — a refusal is a naming
  site.
- **A leg that finishes names the next step, and the step is the skill.** The story
  handback said `close.py story <id> review`, which is `/story-close`'s step 2 — past
  the preflight, the fix-or-ask judgment point and the digest replacement. It now names
  `/story-close`. Verified live on codex-cli 0.150.1, which resolves the token and reads
  the shipped `SKILL.md`. The free leg is deliberately unchanged until `/free-close`
  exists.
- **Sprint cards get a reader who did not write them.** `card-reviewer.md` is a new
  shipped charter, routed from `/sprint-close`, that reads a proposed slate without the
  lead's conclusions and checks slate ordering and funding, AC-to-Verify mapping,
  existing-code premises by executing them, and pins the cards do not name. Its checks
  are written from two measured data sets: this project's own hand-run over the Sprint
  15 slate, and a parallel run on an unrelated project.

Also: this repo's own `lefthook.yml` now reads its test tiers from `.xp/config.yml`
through `run_tier` instead of restating them, which is what the shipped template already
did; the twenty-second component re-cut moves three lines to `close`, total unmoved at
5,570; and `sprint-close/SKILL.md` stops promising a confirming round for lead changes
that `close.py` actually exempts.

## v0.15.0 — each harness can trust what the other is running

Sprint 14, opening and completing Milestone 6. Six cards make installation state,
role readiness, free work and Verify paths explicit across both supported harnesses.
The sprint spends fourteen net shipped lines, raises no total cap, and funds its one
component re-cut from the removal of `--in-place`.

- SessionStart compares the running plugin with the other harness's installed record
  and reports version drift with the install command that repairs it at the scope the
  stale record holds — never `marketplace upgrade`, which exits 0 on a local source
  without touching it. Plugin identity comes from the manifest; records are scoped per
  install; a long-running session is never compared with its own newly updated record;
  and no repository-local path leaks into a consumer install. Absent harness, absent
  plugin, stale plugin and changed installed version remain distinct states, and a
  record whose identity, version or scope is not a plain token reads as unreadable.
- Role preflight now proves the selected harness has this plugin before launching the
  first reviewer, including dry runs. A missing install refuses before any finder,
  verifier or fixer spend, while disabled roles retain their own refusal.
- `xp-setup` offers the normal marketplace install for each configured harness. The
  published Codex path was installed and walked as a consumer would run it.
- `spawn.py --in-place` is gone. The process no longer offers the lead a route to act
  as its own executor; code is written on a branch in a teammate worktree. Ordinary
  story spawn and carded free work retain their handoff and landing paths.
- Every free patch now has a card: mint, amend, drift detection, Review, Verify,
  salvage and the distinct free landing command all use the same lifecycle. The old
  cardless branch is removed, and handoffs name the slugged free id they can land.
- Verify documentation now states that argv runs without a shell from the repository
  root. Subprojects use their runner's working-directory option; the README's `uv
  run --directory` example was walked passing, failing and with the directory option
  removed.
- The fast-tier cost falsifier uses a same-run load control, so host contention does
  not impersonate a suite regression. Fault injection proves suite-only slowdown still
  reds, and timer-dependent watchdog tests remain in the full release tier.

## v0.14.1 — the free leg names its own land command

Patch. One field-reported defect from the only consuming project running this plugin,
and one of its class found beside it at review.

- After a reviewer patch, a FREE card's handoff printed `close.py story <branch-key>
  land` — the story leg's subcommand and the branch-style id, where the free leg takes
  `close.py free <slug> land`. A reader who followed the printed line got a refusal.
  `close.py` built the noun as `story {story_id}` with no arm for the third leg, and
  `free.cmd_review` knew the slug but dropped it where `cmd_land` already threads it
  through. The noun now travels in the launch marker, so `salvage` is fixed by the same
  change and markers written by older versions still record.
- Both free handoffs echo the slug SLUGIFIED. `free start` accepts `Fix Typo`, and only
  the spelling its branch carries survives argparse.

## v0.14.0 — every mechanism has a reader, or it goes

Sprint 13, opening Milestone 5. Six cards. Three remove shipped code; the other three
add an amend verb, a fenced-disposition parser, and the archived-record exclusion that
stops a forged record. The plugin ends the sprint measurably smaller with nothing
lost, and no size cap was raised or re-cut.

- A plan review whose disposition is FENCED in a ```json block is now accepted
  instead of discarded (github issue #38). The findings were written to disk and
  then thrown away, the plan left edited, the round lost, and the wrapper exited 2
  saying no disposition was written — twice costing a full story cycle on one card.
  A report carrying ordinary markdown brackets beside its verdict is accepted too.
  Two decodable JSON OBJECTS still refuse rather than guess which one is the
  verdict, and prose carrying no object at all still refuses exactly as before.
- A [ready] card can be amended honestly: `spawn.py amend <id> --reason '<why>'`
  re-mints the credential, records the reason and the prior text beside it, and
  LEAVES the status unchanged. `spawn.py ready` now refuses to re-mint a card that
  has already been handed to an executor — including one launched with `--in-place`
  — which closes the undocumented two-flip path that re-minted a digest with no
  record of what changed. Free-lane cards keep that path for now.
- An ARCHIVED record's falsifier no longer runs in the sprint-close batch, in either
  the live block form or the compacted stub, and archive now wins over resolution
  when a record carries both. Three archived debts were executing every close and a
  red one would have appended a forged bug claiming the latent problem materialised.
  The cost, recorded deliberately: archiving is now an unchecked done-marker, so "a
  dropped debt that matters will red again" holds only where a test tier covers it.
- The merge-delta FILE STORE and its sprint-review bundle section are gone: they had
  no reader and never fired. The land-time stdout print, which the lead does read,
  and the narrowing that spares a clean sprint-branch overlap a second review round
  both stay.
- The shipped plugin no longer names any test runner. `pytest`, `py.test`, `-k`
  selector syntax and node-id spelling left `work.py`; the rule they enforced is this
  repository's own and its check now lives in this repository's pre-push hook.
- Also removed for want of a reader: the legacy `verdicts[]` recovery arm, the
  session `.alive` touchfile writer, the stale in-repo plan detector and its
  migration command, the stream runner's output-injection parameters, the plan-review
  marker's unread `plan` field, and two argv re-exports. `debt_budget` stays — it has
  a reader in PROCESS.md and was nearly deleted on a premise that measured false.
- The teammate profile target moved 2500 -> 4500. At 2500 it could never be met by
  any spawn — the project's own capped files are ~3240 tokens before a card line — so
  it fired every time and advised retiring a file a constraint pins.

## v0.13.0 — a leg that already ran is not re-bought

Sprint 12. Three cards, one property: no leg in the pipeline pays sweep price for a
confirmation. This closes Milestone 4's last open exit clause.

- A free patch release now pays `tests.story` rather than `tests.full`. `tests.full`
  remains the sprint release boundary alone. A project that configures only `full`
  and no `story` now runs no tier at a free release — loud (one stderr line), and the
  say-so-don't-refuse policy is unchanged, but the leg that hits it is now a release.
- On a sprint integration branch, a clean non-gate overlap with the branch is NAMED to
  the lead at land and written as a story-scoped path list that every sprint-review
  stage reads, instead of buying a second story review round. Gate-file overlap still
  refuses, because it changes what land runs; conflicts still refuse at the trial
  merge; and free and story releases still refuse any overlap, because neither has a
  later sprint review to inherit the signal.
- Records may declare `--covered-by TIER`. When that tier RAN and PASSED in the same
  close, the batch takes its verdict and names the record it trusted instead of
  re-executing the falsifier; when the tier was not run, red, or no longer configured,
  the falsifier runs as before. The author asserts the coverage and nothing checks it —
  `PROCESS.md` says so in those words. Records filed before this version have no
  declaration and execute exactly as they did.
- `config_block_value` no longer silently drops tab-indented keys, which would have
  made an unresolvable tier indistinguishable from an unconfigured one.

## v0.12.0 — projects act, milestones move

Sprint 11. Two stories held out of v0.11.0 until their product contracts were clear.

- Projects can configure one shell-free `lifecycle_command`. It receives
  `sprint-open`, `story-close` or `sprint-close` plus the id and runs before the
  corresponding branch, merge or tag transition. A red command refuses; retries may
  invoke it again, so idempotency and best-effort policy remain project-owned.
- Opening the first scheduled sprint under a planned milestone atomically writes
  `[in-progress]`. Sprint close proposes an explicit `milestone-done` action only
  when every card under the milestone's Sprint sections is done or retired;
  explicitly unscheduled pools do not block it.
- `milestone-done` rechecks scheduled-card terminality, executes the milestone's
  one-line `Done when:` through the shared argv grammar without a shell, and only then
  writes `[done]`. Missing, prose, shell-bearing, non-runnable or red conditions
  refuse without changing the plan.
- Verify now rejects `cd` even on systems that expose `/usr/bin/cd`, preventing tests
  from silently running in the wrong directory. Lifecycle commands also reject
  chains instead of executing only their first argv command.

## v0.11.0 — commands are argv, handbacks are states

Sprint 10. Two stories, plus release-gate repairs found by the durable falsifier
ledger.

- `Verify:` is parsed once as one or more argv commands separated by unquoted `&&`
  and executed sequentially without a shell. Quoted arguments and chains remain;
  expansion, redirection, pipes, backgrounding, substitution and prose are refused at
  ready/review/land before any command runs. Existing cards that relied on shell
  syntax must move that logic into a script and name the script in `Verify:`.
- Executor handbacks now record explicit NEVER SPAWNED, RUNNING, STOPPED and FINISHED
  states. A clean completed story can be resumed by a fresh executor without deleting
  its worktree or branch; launch invalidates an old FINISHED credential by writing
  RUNNING, and a dirty FINISHED tree refuses. Handoff markers created before v0.11.0
  have no `state` and are refused until the lead discards/re-spawns or records a real
  STOPPED recovery—never forge FINISHED.
- This repository's subprocess-heavy fast tier caps xdist at eight workers. On the
  16-core dogfood box, `-n auto` took 135–253s; eight workers ran 934 tests in
  92–110s without weakening the existing 120s/150ms guards.
- Shipped source comments no longer cite project-local constraint numbers. A fresh
  consumer has its own constraint list, so the same index can name a different rule
  or nothing at all.

## v0.10.1 — what a consuming project hits on upgrade

Free patch. Both defects are consumer-facing and v0.10.0 shipped the first one.

- `constraints_size` refused an upgrading project on every commit and named no next
  action: v0.10.0 made `constraints_chars_cap` required, ships it only in the scaffold
  template, and setup never overwrites an existing config. The refusal now names the
  exact line to add. The policy is unchanged — an absent cap still refuses, as an
  unset test tier already does one function down — because defaulting it would impose
  a ceiling the project never chose and treating it as "no cap" would disable, on
  upgrade, the only enforcement that constraints still reach the lead.
- A `Verify:` line carrying backticks or `$(...)` is refused before ready, review and
  land instead of reaching `/bin/sh` as command substitution. Accepted lines keep the
  shell grammar every card relies on, `&&` chains included. This is the substitution
  half of GitHub #14 only: that report's `&&`-chain symptoms are still undiagnosed and
  the issue stays open.

## v0.10.0 — the profile fits the transport, and the sprint branch is per clone

Sprint 9. Five stories, two of them scheduled mid-sprint: one to unblock the close,
one on a bug that surfaced trying to run two sprints at once.

- A confirming sprint round is one story-shaped reviewer over the delta that can FIX
  inside its own round, not a scoped fanout that could only find. `named_paths` is
  deleted; round 1 keeps its four stages.
- The Sprint-8 Codex-lead walk is written down (`docs/AUDIT.md` §10), read from the
  recorded session rather than re-driven. It found that Codex truncates SessionStart
  hook output at 10,000 BYTES — head 4,916 + tail 5,084, identical across six samples
  — with no notice of its own and the middle removed.
- The lead profile is measured and capped in BYTES and now delivers every constraint.
  The digest, recovery block and sprint slice left the profile; `session_start.py
  recover` prints them on a tool channel with its own budget, and PROCESS.md's head
  names it. `constraints_chars_cap` is enforced by the scaffolded git wall.
- Each sprint-review stage resolves its own role (`finder`, `verifier`, `fixer`,
  `closer`), falling back to `reviewer` so a config predating the keys still runs.
- The sprint branch is recorded per clone in the state root, not in tracked config, so
  two clones can run two sprints; a stale tracked key refuses instead of retargeting
  a merge to trunk.

## v0.9.0 — completed work is kept, and the pipeline can close itself

Sprint 8. Four deliberately disjoint stories opened Milestone 4 by preserving work
that a completed leg had already paid for.

- Plan review now stops at its finding bar: addressable findings edit the executor's
  plan, while loud findings remain visible without forcing invented edits or another
  round. Sprint-slate and capacity judgment stay with the lead's card review.
- A sprint-review stage that refuses no longer erases the reports earlier stages
  wrote. The round records that it is incomplete, which stages actually reported,
  and the findings that survive; land refuses that truthful state.
- Pytest falsifiers using `-k` are rejected at filing. Live records were migrated to
  exact node IDs, so renames fail loudly instead of certifying an unrelated test.
- A spawned story can run the plugin copy in its future worktree, including resume
  and free-branch paths. Consuming projects without plugin sources keep the installed
  copy, and the handback tells the lead which root and version every close leg uses.
- Codex now receives this repository's conventions through `AGENTS.md`, which points
  to the shared `CLAUDE.md` rather than duplicating it.
- Sprint close now treats a retired card as terminal. The old done-only check called
  folded work unfinished and stopped this release; an exact regression test holds
  both the retired and active-state arms.

## v0.8.2 — a carded free patch lands where the free legs look for it

- A free patch WITH a card is now spawned onto the branch `free start` cut. Spawn
  derived its own name from the card title and branched from the integration
  target, so the executor's work landed where the free legs refuse it — and the
  lead's own commits on the free branch were absent from it, which made `reset`
  the obvious recovery and a silent way to lose them.
- The branch rule lives in `story_branch`, the one function both spawn and resume
  call, so a stopped free patch still resumes into its own worktree.
- Spawn now reports where that branch went: it says the tree CONTINUES the free
  branch rather than claiming it was cut off the integration target, it names the
  free review leg and the worktree to run it from — the story leg accepts a free
  id and writes the same marker free land reads — and if the lead is standing
  somewhere else, the refusal asks for `git checkout <branch>` instead of leaving
  `git branch -D` as the obvious way past it.

Bug 3dc03ed1 — a review losing its round to a file the lead left before it
started — is NOT fixed here. The attempted narrowing was inert: `close._preflight`
refuses a dirty tree before the reviewer launches, so the baseline is always empty
and the comparison collapses to the old check. Folded into story-054, where
recording the round from the artifacts already on disk is the shape that works.
Its plan-review twin needed no change: that leg compares the tree before and
after, so a file the lead left BEFORE it starts already costs no round, while one
left DURING it still refuses. Constructed both directions to check.

## v0.8.1 — three checks that could not red, and a record that stops growing

- Shipped comments no longer cite constraints by INDEX. Indices are project-local:
  `xp-setup` seeds a starter list and every project grows its own, so our
  "constraint 10" landed in a tree where 10 governs something else entirely.
- A plan review that produced findings is no longer reported as one nobody signed.
  Absent, unreadable and unsigned are three states; the notice enumerated two, and
  a consuming project lost a complete review to it.
- Report list caps now bound the DISPLAY, not the data. Past the cap, findings
  reached no verifier and the "(+N more)" placeholder was judged as if it were one.
- `work.py compact` moves disposed records' prose to `archive.md`, keeping their id,
  disposition and falsifier in `work.md`. The sprint-close corpus is unchanged —
  same falsifiers, same commands — and the archive is written and verified before
  `work.md` is touched. Measured on this repo: 528KB to 350KB.

## v0.8.0 — the harness cannot silently fail to do the work

Sprint 7. Milestone 3 closed: a consuming project ran a full sprint under released
versions and reported it (AUDIT.md §9), hand-steps named as the deliverable.

- A story-close round is refused unless the pipeline ran the card's Verify ITSELF,
  on the tree the round would certify. `blocking: []` used to be the reviewer's own
  word that Verify ran; a field report measured four rounds green with the build dead.
- The reviewer's bound is SILENCE, not a wall clock. A productive reviewer was
  killed twelve minutes after its last commit and the lead was told nothing happened.
  The refusal now names the live log, the salvage route, and `XP_AGENT_TIMEOUT`.
- A killed reviewer's round can be salvaged instead of re-bought.
- A confirming sprint round reads only its delta and re-runs only the finders whose
  paths moved, and the record says it was scoped rather than swept.
- Every leg that FINISHES names the next step, the way a refusing leg already did.
- Codex can spawn codex: DESIGN's "cannot on macOS" was measured against the wrong
  variable and is retired. Codex now runs as executor, nested plan reviewer, and
  story reviewer.
- Test fixtures copy a finished repository instead of rebuilding it: 16.97x on
  fixture cost, ~14% off the tier with six more tests.
- Constraint 12 now says prose that instructs an agent to run something is itself a
  path you must execute before shipping it.

## v0.7.7 — the fixer validates its own patch against the wall

- Both reviewer charters now tell the fixer to EDIT, STAGE, run the repo's commit
  gate over the INDEX, fix what it reports, then diff-and-restore. It still leaves
  the tree unchanged and still never commits, so the motion guard is untouched —
  but a patch that the gate would reject is now caught by the agent that wrote it.
  Staging is the load-bearing word: a commit gate reads the index, so over
  unstaged edits it checks nothing and greens.
- When the gate refuses anyway, the refusal names the gate, quotes the cause with
  ANSI stripped, says how much of the transcript it cut, and names the patch file
  that outlives the undo offered under it — instead of a colour-framed hook
  transcript with the reason twelve lines up.
- Field-reported by a consuming project: a formatter disagreeing about array
  wrapping discarded a whole sprint-review round, closer included.

## v0.7.6 — card review and plan review are two things with two owners

- The lead's review of the sprint slate is the **card review**; `spawn.py ready`
  is the lead's per-card commitment, not a review. The executor's review of its
  own implementation plan keeps the name **plan review**.
- PROCESS.md, TEAMMATE.md and CLAUDE.md now say the lead never writes an
  implementation plan. One word had covered both artifacts, and the lead read it
  as his — measured twice in one week.
- No script, CLI verb or gate changed. `plan_review.py` still serves both.
- AUDIT.md §9 records the field walk: a consuming project ran a full sprint under
  released versions, closing Milestone 3.

## v0.7.5 — one batch verdict, and no silent internal entry points

- Sprint close runs each distinct falsifier once and maps a red verdict back to
  every record that cites it, including the bug Claim it appends.
- Internal shebang-bearing modules refuse direct execution explicitly; the
  sprint-close refusal names `close.py sprint <id> <action>` as its public route.

## v0.7.4 — a leg that stops says so, and one that finishes finishes

- All three hooks share one advisory runner: malformed payloads and crashes remain
  exit-zero but print their traceback, and the terminal-input guard lives once.
- Free post-merge finds a spawned card by its keyed worktree, removes that tree
  and its recorded branch, then independently discharges the free branch.
- The Python cap rises once to 5,500 after the measured audit; exact component
  equality enforces the attributed 1,495/2,245/585/1,175 allocation.

## v0.7.3 — completed work reports itself completed

- Plan review accepts reasons preserved across hard wrapping while still
  refusing reasons absent under whitespace normalization.
- Free post-merge now uses story land's shared worktree teardown and branch
  discharge, reporting teardown failures after continuing cleanup.
- Hooks invoked from a terminal identify their JSON-on-stdin contract and exit
  instead of blocking; piped hook behavior is unchanged.
- `free start` reports whether its optional card already exists in the plan.

## v0.7.2 — the opt-out arrives before the default does

- **Codex sandbox posture is project-selectable.** `codex_sandbox` accepts
  `workspace-write` or `danger-full-access`; the latter remains the default, so
  an existing project gets byte-identical launch argv. Every Codex executor and
  reviewer reports the posture read back from its launched argv. Unknown values
  refuse before a worktree is cut, and `read-only` is refused separately because
  the plugin's roles must write their deliverables. Claude launches are unchanged.
- **Free work uses the same spawned-executor shape as stories.** PROCESS now
  names the path; `free start` refuses slugs whose 20-character truncation would
  detach an optional card, and its nudge places project-owned release artifacts
  before review without prescribing what those artifacts are.
- **A stopped story is taken over, not started again.** `spawn.py resume <id>`
  hands a stopped story's OWN worktree — its commits and its uncommitted work —
  to a fresh teammate, which is told plainly what it inherited and that it is not
  its own. Plain `spawn` still refuses a story that already has a worktree, so
  resume is an explicit verb and never a silent reuse. Before this, a stopped
  story could only be finished by hand or discarded along with its tree.
- The Python sub-budgets were re-cut twice, still totaling 5,000 lines: once to
  fund the close/free surface, then 70 lines misc-to-spawn for the resume work.
  Both were priced against measured occupancy.

## v0.7.1 — the sandbox we never chose, and the rules that never arrived

A patch, not a sprint. Three unrelated defects that each cost a consuming
project on day one, plus one the fix for the second uncovered.

- **Codex teammates and reviewers run unsandboxed.** Every codex leg now
  launches `--sandbox danger-full-access`, and every launch PRINTS the posture,
  read back off the argv actually used. Measured on 0.149.0 with controls:
  under `workspace-write` the Docker socket, loopback TCP and a nested
  `codex exec` are each denied, and one string lifts all three — `--add-dir`
  does not, it grants path writes, not socket-connect capability. This removes
  an inconsistency rather than adding a risk class: the Claude legs already run
  with no OS sandbox, because Claude Code exposes none. **Not yet configurable
  — story-040 owes the opt-out, and until it lands a project cannot decline.**
  Gone with it: the role-keyed `network` argument, which is how the REVIEWER leg
  came to run with no network at all — true, unprinted, and believed backwards.
- **The session digest is REPLACED, and something measures it.** Its size was
  stated in three places and its lifecycle in none, so ours grew to 380 lines
  and 26,797 chars over six sprints and silently evicted four constraints from
  the lead's profile. SessionStart now refuses over the bound, naming the path,
  the count and the bound.
- **The lead profile fits, and VALUES leads it.** `OUTPUT_CAP` 12,000 → 18,000,
  derived rather than aspirational. Order is now contract: VALUES first,
  PROCESS second, neither dropped nor moved. When the cap does bind, the notice
  names every rule it dropped — computed against `constraints.md`, never by
  scanning the cut region, because PROCESS.md carries four lines of the shape a
  constraint has.
- **README says how to launch a Codex lead.** A spawn happens inside the lead's
  own sandbox, so a confined Codex lead can nest neither `codex exec` nor the
  network a nested `claude -p` needs. The flag, and what a Codex lead gives up.
- The push wall re-runs lint and gitleaks, closing the `core.hooksPath` bypass;
  an unreadable session digest costs the digest, not the whole recovery block.

## v0.7.0 — the consumer's copy: what a project that is not us can see

Seven stories. The theme is everything a consuming project hits that we never
do, because we are the only user and our tests build their own fixtures.

- **A worktree's environment is torn down, not just unlinked.** `Worktree
  bootstrap:` has shipped since v0.6.2; teardown was a promise with no code, so a
  project whose bootstrap starts a container outside the checkout was handed an
  obligation nothing discharged. Teardown now runs inside the doomed checkout
  before removal, REPORTS and continues rather than refusing (a refusing teardown
  wedges every close), and gets a wall clock — `teardown_timeout:` in
  `config.yml`, so a project doing heavy lifting raises it rather than forking.
- **An aging config says so.** A `config.yml` scaffolded by an older `xp-setup`
  never gains keys the template adds later, and the refusal named the SHAPE it
  wanted rather than the cause. It now names the key, the file and the line to
  add — and distinguishes a key that is ABSENT because your config predates it
  from one that is MALFORMED because you typed it wrong.
- **Free mode is a one-card sprint.** `close/free.py` was 120 lines re-expressing
  `sprint_close.cmd_land` almost step for step; the duplication is gone, free
  inherits the release-ordering guard rather than taking a fourth copy of it, and
  the tag is cut on the merged sha instead of being a hand-step.
- **The plan review edits the plan instead of arguing about it.** The reviewer
  now writes its findings INTO the draft with their reasons, rather than handing
  them back to the party least able to concede them. Measured across this sprint:
  stories before the change took eight and nine plan rounds; the three after it
  took one each.
- **`spawn` refuses what it cannot read.** A missing `.xp/system.md` read as "no
  bootstrap line" and skipped; a present but non-UTF-8 one tracebacked. Both now
  refuse by name, and the refusal names a command that WORKS in that state — the
  first draft named one that refuses in exactly the state that produces it.
- **A respawned teammate inherits what stopped the last one.** An escalation used
  to cost the successor everything: it re-derived the plan and re-ran the review
  from scratch, though both survived on disk. It now receives its predecessor's
  draft, the findings that stopped it, and the record it filed — and the draft
  lands somewhere `git worktree remove` cannot destroy.
- **The reviewer proposes a patch; the script commits it.** Reviewers are
  read-only on every harness now and emit a patch beside their report;
  `close.py` applies and commits it under the reviewer identity. That retires the
  injected `GIT_AUTHOR_*` credential, the linked-worktree index write a sandboxed
  codex reviewer could not perform, and an after-the-fact authorship scan.
- **The push wall re-checks what a skipped commit hook would have caught.**
  `git -c core.hooksPath=<nonexistent> commit` runs no hooks and exits 0 — a
  silent equivalent of `--no-verify`. `pre-push` ran neither lint nor gitleaks, so
  a bypassed commit carried secrets to the remote. It now re-runs both: the ACT
  leaves no trace, but every gate here is a pure function of the tree, so the
  OUTCOME still can be checked.
- **Smaller, and consumer-facing:** a duplicated `Worktree` label is refused
  naming both lines instead of silently resolving to the first; a missing release
  manifest is reported as missing rather than unreadable; the reviewer's
  wall-clock refusal names `XP_AGENT_TIMEOUT`, the knob that moves it; records
  hold 4,000 chars and the session start names eight of them rather than three;
  and `PROCESS.md` names every skill it ships.

## v0.6.5 — a teammate that stops and says so is escalating, not failing

- **An escalation is no longer reported as a failed run.** `TEAMMATE.md` tells a
  blocked teammate to say so, file a note, and stop — and `spawn.py` then refused
  that exact handback ("the teammate made no commits of its own"), stranding the
  worktree for the lead to salvage by hand. Reported from the field at real cost:
  four runs, three with zero commits, two of them correct escalations, one
  carrying a plan three review rounds deep. A record filed during the run now
  turns that refusal into a reported escalation naming the records to read, the
  work left behind, and exit 3. A teammate that simply did not finish, and said
  nothing, is refused exactly as before — and a run that filed a record and then
  DIED is reported as that, with the harness's exit status, rather than as a stop
  it chose.
- **Python older than 3.11 now refuses by name instead of tracebacking.** Twelve
  of the thirteen shipped scripts died on 3.9 with `unsupported operand type(s)
  for |` — and `python3` on a stock Mac *is* 3.9. The README asked for 3.11+ and
  nothing enforced it, so a consuming project met a TypeError that named nothing:
  `setup.py` could not scaffold, and the SessionStart hook failed before its own
  "never break a session" guard could catch it. Now it says which interpreter it
  found and what it needs — on every entry point, including `plan_review.py`, the
  one leg `TEAMMATE.md` prints, which reached its own annotations first.
- **The v0.6.4 note that the Verify refusal "moved" to the mint was imprecise.**
  It was added at the mint and kept at land — one rule at two depths.

## v0.6.4 — the plan review survives the harness, and says so when it doesn't

- **The mandatory plan review now outlives the call that started it.** Two field
  failures, one per harness, on the same step. Under codex, a shell call's
  timeout is a per-call value *the model supplies* — ~10 seconds by default, and
  a teammate guessed 120s, lost, guessed 180s and lost again against a review
  that runs minutes. Under claude, a headless run ends when the model yields, so
  a teammate that backgrounded the review and yielded orphaned it. `plan_review.py`
  now detaches the review into its own session and waits on it; a call cut short
  loses nothing, and running it again rejoins the review in progress rather than
  starting a second one.
- **A review that dies reaches the lead.** The evidence of a skipped gate is an
  absence, and absences leave no artifact — so a marker is written at launch and
  cleared only when the review's own guards are satisfied. `close.py`'s review leg
  reports it to the lead and puts it in the story reviewer's bundle. Both field
  failures had been caught only by luck; one more commit and a story whose
  mandatory review never ran would have been accepted silently.
- **`unified_exec` is no longer disabled on codex spawns.** It was disabled to
  protect `PreToolUse`, and this plugin ships no PreToolUse hook — what binds a
  codex leg is `close.py` running Verify and the git-hook wall, neither reachable
  from `write_stdin`. An outdated bar with a measured cost.
- **A `Verify:` line whose commands are bulleted below it no longer reads as
  missing.** It parsed empty, indistinguishable from no line at all, and refused
  at *land* — after the story was written and reviewed — saying "has no Verify:
  line" about a card that visibly has one. The refusal moved to the credential
  mint, so an unverifiable card is stopped before a teammate is ever spawned, and
  the two states now say different things. The template that taught the form says
  the line is load-bearing, and a test feeds the shipped card to the real gate.

## v0.6.3 — one implementation of each rule, and room to work in

- **A missing plan reads the same at every leg.** Six commands answer "this
  clone has no plan", and `close.py story <id> land` had lost half of that
  answer — the half naming what to check. It is the leg reached last, so the
  story furthest along got the least help. All six now share one wording, and a
  test runs every leg against a plan-less clone and compares what they say.
- **Internal consolidation, no behavior change.** The status flip, the
  stream-JSON line decode and the record lookup behind `work.py resolve` /
  `archive` each had more than one implementation; they now have one apiece. A
  helper nothing called and a per-harness flag that was true for every harness
  are gone.
- **Budget re-allocation.** The hook layer was allocated 1,000 lines and
  measures 416, so 350 moved to the components that are actually growing. The
  5,000-line total is unchanged — this only corrects a five-sprint-old guess
  about where those lines would be needed.

## v0.6.2 — the bootstrap line the template taught was unreadable

- **`Worktree bootstrap:` is read past markdown emphasis.** `templates/system.md`
  bolds every field it teaches — `**Product**`, `**Stack**`, `**Layout**` — and
  the parser matched the literal substring `Worktree bootstrap:`, which a bolded
  label does not contain: the `**` sits between label and colon. It returned
  empty, and spawn's `if command := ...` skipped the block. No bootstrap, no
  warning, no nonzero exit — a teammate launched into a tree nothing prepared.
  Every repo that wrote the line in the template's own bolded style was
  affected; one written unbolded — the form every test used — was not.
- **An unreadable line now refuses; an absent one still doesn't.** Empty
  conflated "no line" (legitimate — a project may need no bootstrap) with "a
  line I could not read" (a defect), which is what made the above silent. `none`
  stays a legitimate no-op so the refusal cannot block a project that correctly
  has nothing to run. A parse failure refuses BEFORE the worktree is cut, or the
  corrected retry would hit `already spawned` and name the wrong problem.
- **Prose with two backticked spans no longer executes.** The value had to be
  one backticked command, but the match was greedy: the template's own example
  wording — `` `npm ci` or `uv sync` `` — matched end to end and ran verbatim
  under a shell, where the inner backticks are command substitution.
- **The shipped template is now exercised.** Every bootstrap test wrote its own
  unbolded line, so the form the template *teaches* had never once been fed to
  the parser — vacuous by fixture. A dogfood arm takes the template's own label
  verbatim, so a reformat reds here rather than in a consuming project.

## v0.6.1 — the wall stops reporting green having run nothing

- **The scaffolded wall refuses instead of warning.** `hook-lib.sh` had two
  paths that passed a commit having run nothing: a missing `gitleaks` warned
  and fell through, and an unset or still-`EDIT-ME` test tier returned 0. The
  second fired on a *freshly scaffolded* repo — setup seeds `EDIT-ME`, so the
  wall installed, the first commit passed, and no test had ever run. Both now
  exit 1 naming their next action. Reported from the field on a real monorepo.
- **A `#` inside a word is no longer read as a YAML comment.** `tier_cmd` cut
  the tier value at any `#`; YAML opens a comment only at a whitespace-preceded
  one. A tier carrying an inline env var whose password held a `#` truncated to
  a bare `VAR=value` — a valid shell command that assigns, exits 0 and runs no
  test. The same false green as the two legs above, reached from the parser
  instead of the guard. Trailing `  # ...` comments strip exactly as before.
- **`xp-setup` stops naming a hook it declined to write.** Where existing hook
  routing is found, the closing advice no longer says "add your linter to the
  pre-commit hook"; it names the actual task — point `.xp/config.yml`'s tiers
  at the existing wall's own commands, so the two cannot drift into different
  definitions of "fast".
- **`trunk:` — release where you actually integrate.** Sprint close targeted
  git's default branch with no way to say otherwise, so a repo integrating on
  `develop` could open a sprint, land stories, and then be refused at close for
  trying to tag a branch containing none of the sprint. `trunk:` in config.yml
  names where sprints land and releases tag; configured-but-absent refuses
  rather than falling back, since silently releasing to `main` is the failure
  it exists to prevent. Deliberately ONE branch — cutting `develop -> main`
  stays your release process, not xp's.
- **The release identity is now enforced, not just mandated.** v0.6.0 was
  tagged with the manifest still at 0.5.0; since the manifest version keys the
  consumer's plugin cache, that tag shipped the previous copy under a new name.
  `tests/test_release.py` refuses a manifest behind the latest tag, or a
  version with no CHANGELOG entry (constraint 14).

## v0.6.0 — either harness, any role (Sprint 5)

- **Headless plan review** (`plan_review.py`): the last subagent riding a
  harness tool became a config role — `harness/model/effort` like every other
  agent, launched through the shared runner. A codex teammate can now run its
  mandatory plan review (via a claude reviewer — see below).
- **Per-story `Reviewer:` card lines**, alongside `Executor:` — one card can
  say "author codex, review claude" and the next the inverse.
- **Every spawned agent streams**: one runner (`run_stream`) for teammates,
  reviewers, and plan reviewers — live tailable logs per role under the data
  root, native harness transcript pointers recorded, wall clocks preserved.
  Authored by codex (`gpt-5.6-sol`), reviewed by claude — the project's
  original pairing, now the default configuration.
- **The environment file** (`env.json` in the data root): setup seeds it,
  SessionStart refreshes it on both harnesses; processes nothing spawned
  (codex-lead scripts, hooks) resolve the installed plugin root through a
  validating reader that refuses stale or skewed installs loudly.
- **Codex sandbox facts, measured and shipped**: commits from linked
  worktrees need the git-common-dir widening (applied automatically,
  cwd-keyed); the executor leg gets sandbox network access (nested reviews
  need the API); codex cannot nest codex on macOS (upstream app-server
  limitation) — nested spawns route cross-harness by config.
- **`Files:` is a starting map, not a permission list**: implementations
  extend it and report deviations; an undeclared `.xp/` path remains a hard
  stop. (Measured cost of the old rule: ~500k tokens of plan-gate restarts.)
- Fast tier re-pinned at 55s for a doubled suite; 11 deep land-leg
  integration tests moved to the pre-push tier.

## v0.5.1 — free-mode patch release

- Duplicate story ids refuse instead of splitting across readers (the
  scaffold skeleton no longer collides with the natural first id). The first
  release shipped through `close.py free` — the card-less path to main.

## v0.5.0 — usable elsewhere, parallel here (Sprint 4)

- Per-clone execution plans; overlap-based land guards (trial merge, tier on
  the merged tree, ancestor and authorship checks); `[ready]` as a minted
  credential; one release review with angles (find → judge → fix → clear,
  security among the angles); codex as spawnable executor and reviewer with
  measured env-policy pins; codex as native lead (one hooks file, honest
  degradations); free mode.

## v0.4.0 and earlier

- The self-hosting core: story/sprint close pipelines, fixing reviewers,
  the git-hook wall, declarative records with falsifiers, the size ratchet.
