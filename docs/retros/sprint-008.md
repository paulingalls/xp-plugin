# Sprint 8 retro — completed work is kept, and the pipeline can close itself

Four scheduled cards landed: 052, 054, 057, and 059. Three deliberately deferred
cards—053, 055, and 058—are queued under Sprint 9 for its card review. The sprint
also added `AGENTS.md` and fixed the retired-card defect that first blocked this close.

## 1. What the process caught

**Fault injection at story review earned its cost again.** The 052 reviewer caught
that moving sprint judgment out of plan review had also deleted the lead's only
statement that card review covers the whole slate. The 054 reviewer found a swallowed
dry-run refusal, duplicated salvaged findings, false stage coverage, and an abort path
that recorded a round silently. The 057 reviewer showed the timing proof could pass
the old implementation and forced its two causal arms apart. The 059 confirming
review deleted its own `resuming` condition and all 887 tests stayed green, then added
the constructed resume case that reds against that deletion.

**The git-hook wall kept reviewer fixes honest.** Reviewer patches repeatedly met the
same lint, secret, fast-test, full-test, and size gates as authored code. The release
tree finishes at 889 tests before the retro diff.

## 2. What it missed

**Note triage missed a defect that then repeated.** Note `e34104c2` recorded during
Sprint 7 that sprint membership treated every non-done status as unfinished. It was
worked around, remained live, and Sprint 8 close failed on the same class: deferred
planned cards and a folded retired card were both called unfinished. Triage—not a new
review angle—should have promoted or retired that note before another sprint inherited
it. The fix now enumerates retired as terminal, and constraint 15 generalizes the
lesson so status machines cannot use “not done” as a substitute for their vocabulary.

**Parallel code lanes were mistaken for parallel gates.** The four story diffs were
file-disjoint, but every commit and land shared `pytest -n auto` and wall-clock timing
tests. Running close gates concurrently slowed them sharply and produced timing reds
while CPU remained modest. The missing mechanism was operational guidance visible to
the lead, not more machine capacity.

**Codex entered without repository conventions.** The plugin injected process state,
but Codex natively reads `AGENTS.md`, not `CLAUDE.md`; this repository had only the
latter. The portable pointer added this sprint makes the two harnesses share one source.

## 3. What earned its place, and what cost more than it returned

**Earned: constraint 2, fault-inject every guard.** It found silent certification
failures in every substantial story and produced tests that discriminate the broken
implementation from the fixed one.

**Cost more than it returned: “file-disjoint means no ordering.”** That Sprint 8 card
premise was true for merges and false for gates. It encouraged parallel close work,
lost useful reviewer progress to orchestration, and made timing tests measure another
gate rather than their subject. The replacement is explicit in system context: two
analysis/review streams are allowed, one test gate is not.

## 4. The proposed diff

- `.xp/constraints.md` #15 broadens absent-versus-unreadable into exhaustive state
  distinctions: missing/unreadable and retired/unfinished are instances of one rule.
- `.xp/system.md` replaces duplicated test-tier spellings with the measured concurrency
  and unbounded-review guidance. The load-bearing bootstrap field remains.
- `plugins/xp-plugin/.claude-plugin/plugin.json` and `CHANGELOG.md` name v0.9.0 before
  review, so the tag, manifest, and release notes can still name one release.

## 5. What carries

The close repaired six missing bug resolutions whose exact falsifiers were already
green. Twelve debts remain live; their falsifiers are green and none crosses the
silent-or-corrupting bar during this close. Sprint 9 currently queues three feature
cards, so `debt_budget` 0.2 × 3 is below one and schedules no debt. Its card review
will reconsider the debt slate rather than inheriting a choice made during release.
