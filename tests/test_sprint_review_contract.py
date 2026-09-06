"""What the sprint review leg may not do — move the tree, rewrite this sprint's
cards, drop a resolution — and the charter and prose that state the same bound."""

import json

from close_helpers import launches
from sprint_helpers import (
    PLUGIN,
    WORK_SECTION,
    committing_stub,
    head,
    make_repo,
    marker_path,
    section,
    sprint,
    work,
)


class TestResolutionsAreCarried:
    """AC 5. Three of three resolutions that needed independent reading were
    caught by a READER, never by resolve()'s green-check (7df6b116, b9382e2d,
    997c0c63) — and resolutions filed AT the close are read by no reviewer at
    all, which is the moment they are most likely to be falsified."""

    def _resolved_twice(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        work(
            repo,
            env,
            "bug",
            "--claim",
            "THE-ORIGINAL-CLAIM",
            "--falsifier",
            "false # ORIGINAL-FALSIFIER",
            "--files",
            "a.py",
        )
        ref = work(repo, env, "list").stdout.split()[0]
        for attempt in ("SUPERSEDED-TRY", "LATEST-TRY"):
            assert (
                work(
                    repo, env, "resolve", "--ref", ref, "--falsifier", f"true # {attempt}"
                ).returncode
                == 0
            )
        assert sprint(repo, env, "review").returncode == 0
        return ref, launches(tmp_path)[0]["stdin"]

    def test_the_bundle_carries_the_claim_and_original_falsifier_it_replaced(self, tmp_path):
        """corpus() cannot serve this: substitution is exactly where it discards
        the original, and the original is what makes the swap judgeable."""
        ref, bundle = self._resolved_twice(tmp_path)
        body = section(bundle, "Resolutions filed during the sprint", WORK_SECTION)
        assert ref in body
        assert "THE-ORIGINAL-CLAIM" in body
        assert "ORIGINAL-FALSIFIER" in body, "no original: the reader cannot judge the swap"
        assert "LATEST-TRY" in body

    def test_only_the_latest_resolution_per_record_survives(self, tmp_path):
        _ref, bundle = self._resolved_twice(tmp_path)
        assert "SUPERSEDED-TRY" not in bundle, "every superseded correction shipped verbatim"

    def test_resolved_blocks_are_filtered_out_of_the_raw_work_md_section(self, tmp_path):
        """They are work.md entries, so shipping both hands the reviewer the same
        substitution twice and invites the re-litigation the dedup prevents."""
        repo, env, _g = make_repo(tmp_path)
        work(repo, env, "bug", "--claim", "c", "--falsifier", "false", "--files", "a.py")
        ref = work(repo, env, "list").stdout.split()[0]
        work(repo, env, "resolve", "--ref", ref, "--falsifier", "true # THE-REPLACEMENT")
        work(repo, env, "note", "A-PLAIN-NOTE")
        assert sprint(repo, env, "review").returncode == 0
        raw = section(launches(tmp_path)[0]["stdin"], WORK_SECTION, "JUDGMENT")
        assert "A-PLAIN-NOTE" in raw, "the raw section lost the entries it exists to carry"
        assert "## resolved " not in raw


class TestMotionIsBoundedByAMechanism:
    """story-014's AC 2, surviving story-022's reversal: report-only is gone — the
    fixer commits — so what the leg still refuses is motion nobody signed for. The
    agent file's `tools:` line bounds nothing here: review.run launches a TOP-LEVEL
    claude session that never loads the agent file, which is why charter() inlines
    it, and why authorship rather than a tool list is the bound."""

    def test_a_reviewer_that_COMMITS_is_refused_and_recorded_incomplete(self, tmp_path):
        """This is ALSO where the pre-launch head capture is pinned. A stub that
        never commits cannot tell a pre-launch head from a post-run one, so the
        test that asserted the ordering directly was vacuous and was deleted in
        round 1; the undo sha in the refusal is what reds when it regresses."""
        repo, env, _g = make_repo(tmp_path)
        committing_stub(
            tmp_path,
            "open('snuck.py','w').write('X = 1\\n')\n"
            "os.system('git add -A && git commit -qm snuck')\n",
        )
        before = head(repo, env)
        r = sprint(repo, env, "review")
        assert r.returncode == 2, r.stdout
        assert before[:8] in r.stderr, "the undo names no sha to reset to"
        assert json.loads(marker_path(tmp_path).read_text())["rounds"][-1]["incomplete"]

    def test_a_reviewer_that_leaves_the_tree_DIRTY_is_refused(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        committing_stub(tmp_path, "open('src.py','a').write('# edited\\n')\n")
        r = sprint(repo, env, "review")
        assert r.returncode == 2 and "dirty" in r.stderr
        assert json.loads(marker_path(tmp_path).read_text())["rounds"][-1]["incomplete"]

    def test_an_incomplete_round_is_LABELLED_where_the_next_round_reads_it(self, tmp_path):
        """The sprint prompt must label candidates no verifier ever judged."""
        import bookkeep

        repo, env, _g = make_repo(tmp_path)
        candidates = {"fixed": [], "blocking": ["a silent one"], "noted": []}
        committing_stub(tmp_path, "open('src.py','a').write('# edited\\n')\n", report=candidates)
        assert sprint(repo, env, "review").returncode == 2
        rounds = json.loads(marker_path(tmp_path).read_text())["rounds"]
        assert "a silent one" in (body := bookkeep.render_sprint_prior(rounds))
        assert "INCOMPLETE after find-security" in body, body

    def test_a_reviewer_that_rewrites_the_MARKER_is_refused(self, tmp_path):
        """The marker is outside the repo, no diff shows it, and it is the file
        land reads for rounds and blocking[] — a review may not move its own gate."""
        repo, env, _g = make_repo(tmp_path)
        path = marker_path(tmp_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"rounds": [], "shown_sha": "x"}))
        committing_stub(
            tmp_path,
            f"open({str(path)!r},'w').write('{json.dumps({'rounds': [], 'shown_sha': 'y'})}')\n",
        )
        r = sprint(repo, env, "review")
        assert r.returncode == 2 and "marker" in r.stderr

    def _plan_rewriting_stub(self, tmp_path, old, new):
        committing_stub(
            tmp_path,
            "p = os.environ['XP_DATA'] + '/plan.md'\n"
            # read BEFORE opening for write: `open(p,'w')` truncates as its own
            # expression, so the one-liner spelling wipes the plan and every arm
            # refuses, red and green alike
            "t = open(p).read()\n"
            f"open(p, 'w').write(t.replace({old!r}, {new!r}))\n",
        )

    def test_a_reviewer_that_rewrites_a_card_of_THIS_sprint_is_refused(self, tmp_path):
        """story-019 took the plan out of the repo, so the tree stays clean and
        HEAD stays put while a reviewer rewrites the cards it is reporting on —
        every check above passes and the release ships against a plan nobody read.
        The cards digest is what remains, and until this test nothing exercised
        it: `if False and sprint_cards(...) != cards` passed all 365."""
        repo, env, _g = make_repo(tmp_path)
        self._plan_rewriting_stub(tmp_path, "story-042 — done thing", "story-042 — REWRITTEN")
        r = sprint(repo, env, "review")
        assert r.returncode == 2 and "cards changed" in r.stderr
        assert json.loads(marker_path(tmp_path).read_text())["rounds"][-1]["incomplete"]

    def test_a_reviewer_is_NOT_refused_over_ANOTHER_sprints_card(self, tmp_path):
        """The green twin, and the reason the digest is sprint-scoped: the plan is
        one shared file now, so digesting the whole of it would let any lane's flip
        refuse an unrelated release review — the project-global mutable gate
        constraint 10 forbids. story-099 is [ready] in Sprint 3, not this one."""
        repo, env, _g = make_repo(tmp_path)
        self._plan_rewriting_stub(tmp_path, "story-099 — not this sprint", "story-099 — MOVED")
        r = sprint(repo, env, "review")
        assert r.returncode == 0, r.stderr + r.stdout


class TestSprintCharter:
    def test_what_every_stage_shares_is_a_delta_not_a_second_charter(self):
        """An opus executor with no bound modelled this on story-reviewer.md (712
        words). Four stages now share ONE preamble, and it is the part every
        launch pays for — the per-stage sections have their own cap in
        test_review.py. `report-only` is gone from it deliberately: the fixer
        commits, and a charter still claiming otherwise contradicts the gate."""
        text = (PLUGIN / "agents" / "sprint-reviewer.md").read_text()
        shared = text.split("---", 2)[2].split("\n## ")[0]
        assert len(shared.split()) <= 150, f"{len(shared.split())} words: a preamble, not a charter"
        assert "report-only" not in shared.lower(), "the fixer commits; this leg is not report-only"
        assert "JUDGMENT.md" in shared, "the bar and rubric pointer drifted"
        assert "Round 1" in shared and "Later rounds use one" in shared
        assert "story-shaped reviewer" in shared and "fix inside its round" in shared
        # the report SHAPE as the stage must write it, not the bucket names in
        # prose: `noted` reads fine in a sentence that never states the JSON
        for token in ('"fixed"', '"blocking"', '"noted"'):
            assert token in shared, f"the charter never names {token}"
        closer = text.split("\n## closer\n", 1)[1]
        assert '"clearable_by_full"' in closer and "tests.full" in closer
        assert '"clearable_by_full"' in shared and "only `closer`" in shared


class TestShippedProse:
    def test_the_sprint_close_skill_names_the_human_only_steps(self):
        """The two reviews stopped being human-only at story-014 — the pipeline
        marshals them. What a script still cannot absorb (constraint 7) is note
        triage and the retro narrative, so those are what this pins now."""
        skill = (PLUGIN / "skills" / "sprint-close" / "SKILL.md").read_text().lower()
        assert "note triage" in skill and "retro" in skill
        assert "narrative is the part" in skill, "the judgment step lost its reason"

    def test_judgment_carries_the_record_lifecycle_and_the_polarity_contract(self):
        judgment = (PLUGIN / "JUDGMENT.md").read_text()
        assert "resolve" in judgment, (
            "a verb in work.py and not in JUDGMENT.md is one rule, two impls"
        )
        assert "still OK" in judgment, "the polarity contract belongs where the filer reads it"
