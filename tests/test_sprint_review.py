"""story-014: the sprint close marshals its reviews.
Split from test_sprint_close.py at sprint-004 open."""

import json
import subprocess
import sys

from close_helpers import launches
from spawn_helpers import stub_codex
from sprint_helpers import (  # noqa: F401
    CLOSE,
    CONFIG,
    PLAN,
    PLUGIN,
    SPRINT_ID,
    WORK,
    WORK_SECTION,
    committing_stub,
    head,
    make_repo,
    marker_path,
    record_reviews,
    section,
    snapshot,
    sprint,
    stage_key,
    staged_stub,
    work,
)

CLEAN = {"fixed": [], "blocking": [], "noted": []}
DELTA = "The delta since the last recorded round"


class TestReviewLeg:
    """story-014, revised at story-022: the sprint close marshals ONE review."""

    def test_an_applied_fix_handoff_names_the_leads_obligation(self, tmp_path):
        lines = []
        for root in (tmp_path / "first", tmp_path / "second"):
            root.mkdir()
            repo, env, _g = make_repo(root)
            report = {"fixed": ["FIXED"], "blocking": [], "noted": []}
            staged_stub(
                root,
                patches=[("fix", "src.py", "C = 2")],
                find={"fixed": [], "blocking": ["FIXED"], "noted": []},
                verify={"fixed": [], "blocking": ["FIXED"], "noted": []},
                fix=report,
            )
            result = sprint(repo, env, "review")
            assert result.returncode == 0, result.stderr
            line = next(line for line in result.stdout.splitlines() if "full diff" in line)
            diff = root / "data" / "reports" / "sprint" / "2.fix.round-1.diff"
            assert str(diff) in line and diff.is_file()
            assert "close.py sprint 2 land" in line and "landing accepts" in line
            lines.append(line)
        assert lines[0] != lines[1]

    def test_a_round_without_its_handoff_diff_is_incomplete(self, tmp_path):
        """And the round does NOT claim the fix. That write rolls the fixer's
        commit back when it fails, so a round naming it in `fixed` — in the marker
        AND in the git-versioned merge body — outlives every artifact a later
        reader could check it against. The findings that survive still must."""
        repo, env, _g = make_repo(tmp_path)
        before = head(repo, env)
        staged_stub(
            tmp_path,
            patches=[("fix", "src.py", "C = 2")],
            find={"fixed": [], "blocking": ["FIXED"], "noted": []},
            verify={"fixed": [], "blocking": ["FIXED"], "noted": []},
            fix={"fixed": ["FIXED"], "blocking": [], "noted": []},
        )
        diff = tmp_path / "data" / "reports" / "sprint" / "2.fix.round-1.diff"
        diff.mkdir(parents=True)
        result = sprint(repo, env, "review")
        assert result.returncode == 2 and "could not write reviewer handoff" in result.stderr
        assert head(repo, env) == before
        round_ = json.loads(marker_path(tmp_path).read_text())["rounds"][-1]
        assert round_["incomplete"] and round_["blocking"] == ["FIXED"]
        assert round_["fixed"] == [] and "fix" not in round_["stages"], round_
        assert sprint(repo, env, "land", "--dry-run").returncode == 2

    def test_a_stage_that_DIES_offers_no_undo_spanning_the_applied_fix(self, tmp_path):
        """A harness error is refused from the STAGE's head, like every other
        refusal in the leg. Measured from the round's start instead, a closer that
        touched nothing prints `git reset --hard <round base>` — an undo that
        discards the fixer commit the same round records under `fixed`."""
        repo, env, _g = make_repo(tmp_path)
        before = head(repo, env)
        staged_stub(
            tmp_path,
            patches=[("fix", "src.py", "C = 2")],
            find={"fixed": [], "blocking": ["F"], "noted": []},
            verify={"fixed": [], "blocking": ["F"], "noted": []},
            fix={"fixed": ["F"], "blocking": [], "noted": []},
        )
        claude = tmp_path / "bin" / "claude"
        claude.write_text(claude.read_text() + "sys.exit(1 if key == 'close' else 0)\n")
        claude.chmod(0o755)
        r = sprint(repo, env, "review")
        assert r.returncode == 2 and "reviewer exited 1" in r.stderr, r.stderr
        assert head(repo, env) != before, "no applied fix for an undo to span"
        assert "git reset --hard" not in r.stderr and before[:8] not in r.stderr, r.stderr

    def test_the_bundle_diffs_against_the_DEFAULT_branch_not_the_integration_target(self, tmp_path):
        """Under `release: sprint`, integration_target() returns the SPRINT branch
        and the fixture is ON it — so that diff is EMPTY and the reviewer would
        certify nothing. A header-grep assertion passes over an empty diff, which
        is bug c9b48a66's own failure mode; a hardcoded "main" passes vacuously
        here and breaks a `master` consumer. So: a string only a sprint-branch
        commit carries."""
        repo, env, _g = make_repo(tmp_path)
        r = sprint(repo, env, "review")
        assert r.returncode == 0, r.stderr
        assert "SPRINT-ONLY-SENTINEL" in launches(tmp_path)[0]["stdin"]

    def test_the_bundle_carries_the_cards_constraints_and_system(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        assert sprint(repo, env, "review").returncode == 0
        bundle = launches(tmp_path)[0]["stdin"]
        assert "CONSTRAINT-SENTINEL" in bundle and "SYSTEM-SENTINEL" in bundle
        assert "story-042 — done thing" in bundle, "the sprint's story cards"
        assert "story-099" not in bundle, "another sprint's card rode along"
        assert "## JUDGMENT\n\n" in bundle and "Polarity" in bundle
        assert "## PROCESS\n\n" not in bundle

    def test_no_sprint_bundle_asks_for_a_merge_delta(self, tmp_path):
        """Planted, because a project upgrading from v0.13.0 still HAS the store on
        disk — nothing deletes it, so absence over an empty root proves nothing."""
        repo, env, _g = make_repo(tmp_path)
        stale = tmp_path / "data" / "reports" / "merge" / "story-042.txt"
        stale.parent.mkdir(parents=True)
        stale.write_text("STALE-MERGE-DELTA.py\n")
        assert sprint(repo, env, "review").returncode == 0
        bundles = [launch["stdin"] for launch in launches(tmp_path)]
        assert bundles
        for bundle in bundles:
            assert "Merge deltas not covered by story review" not in bundle
            assert "STALE-MERGE-DELTA.py" not in bundle

    def test_a_story_cannot_shadow_the_sprints_report_or_marker_key(self, tmp_path):
        """Constraint 10, fault-injected against the id that would collide: a
        story literally named `sprint-2`. BOTH keys — scoping the report and
        not the marker hands the land gate the collision the report just refused.
        Driven through both real legs, because comparing two Path expressions
        holds even against an implementation nobody can reach."""
        plan = PLAN.replace(
            "#### story-043 — also done   [done]",
            "#### story-043 — also done   [done]\n"
            "#### sprint-2 — the colliding id   [in-progress]\nVerify: true",
        )
        repo, env, g = make_repo(tmp_path, plan=plan)
        g("checkout", "-qb", "story-branch")
        story = subprocess.run(
            [sys.executable, str(CLOSE), "story", "sprint-2", "review"],
            cwd=repo,
            env=env,
            capture_output=True,
            text=True,
        )
        assert story.returncode == 0, story.stderr
        g("checkout", "-q", "sprint-002")
        assert sprint(repo, env, "review").returncode == 0
        data = tmp_path / "data"
        story_reports = sorted(p.name for p in (data / "reports").glob("*.json"))
        sprint_reports = sorted(p.name for p in (data / "reports" / "sprint").glob("*.json"))
        markers = sorted(p.name for p in (data / "markers").rglob("*.json"))
        assert story_reports == ["sprint-2.round-1.json"], story_reports
        assert sprint_reports and all(n.startswith("2.") for n in sprint_reports), sprint_reports
        assert len(markers) == 2, f"the sprint and the story shared a marker key: {markers}"
        assert marker_path(tmp_path).exists()

    def test_the_review_leg_run_from_the_default_branch_is_refused(self, tmp_path):
        """close.py:186 has this guard for the story leg. Without it the diff is
        empty and land pushes whatever branch HEAD happens to be on."""
        repo, env, g = make_repo(tmp_path)
        g("checkout", "-q", "main")
        r = sprint(repo, env, "review")
        assert r.returncode == 2 and "main" in r.stderr
        assert launches(tmp_path) == [], "spawned a reviewer over an empty diff"

    def test_a_dirty_tree_is_refused_before_the_reviewer_is_launched(self, tmp_path):
        """Untested until round 1: deleting this guard left all 54 green. Without
        it the leg spends a whole review and only then refuses, on dirt the lead
        may have left."""
        repo, env, _g = make_repo(tmp_path)
        (repo / "src.py").write_text("A = 1\nUNCOMMITTED = 2\n")
        r = sprint(repo, env, "review")
        assert r.returncode == 2 and "dirty" in r.stderr
        assert launches(tmp_path) == [], "reviewed a tree that was already dirty"

    def test_a_sprint_id_with_no_section_in_the_plan_is_refused(self, tmp_path):
        """Also untested until round 1. cmd_start has this guard; the review leg
        would otherwise spawn over empty cards and record coverage for a sprint
        that does not exist, which sprint land then honours."""
        repo, env, _g = make_repo(tmp_path)
        r = sprint(repo, env, "review", sprint_id="99")
        assert r.returncode == 2 and "99" in r.stderr
        assert launches(tmp_path) == []

    def test_dry_run_launches_nothing_and_records_nothing(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        r = sprint(repo, env, "review", "--dry-run")
        assert r.returncode == 0, r.stderr
        assert launches(tmp_path) == []
        assert not marker_path(tmp_path).exists()

    def test_a_dry_run_still_refuses_what_would_stop_the_real_one(self, tmp_path):
        """A preview exists to say what the real run does. review.run resolves the
        harness BEFORE it honours dry_run, so its error is the one thing a preview
        can know; swallowing it greens the command whose whole job is the warning."""
        bad = CONFIG.replace("reviewer: claude/opus", "reviewer: codex/gpt-5.6-terra/high")
        repo, env, _g = make_repo(tmp_path, config=bad + "codex_sandbox: broken\n")
        stub_codex(tmp_path)
        r = sprint(repo, env, "review", "--dry-run")
        assert r.returncode == 2, r.stdout
        assert "codex_sandbox" in r.stderr and "broken" in r.stderr, r.stderr

    def test_a_stage_that_wrote_NO_report_is_not_named_among_the_stages_that_ran(self, tmp_path):
        """`stages` is what the lead reads to see what the round covers, and the
        closer is the stage that exists to catch the fixer. A closer that produced
        nothing is exactly the coverage the lead must not be told it has."""
        repo, env, _g = make_repo(tmp_path)
        staged_stub(tmp_path)
        claude = tmp_path / "bin" / "claude"
        write = "open(m.group(1).strip(), 'w').write(json.dumps(report))"
        claude.write_text(claude.read_text().replace(write, f"None if key == 'close' else {write}"))
        claude.chmod(0o755)
        r = sprint(repo, env, "review")
        assert r.returncode == 2 and "wrote no report" in r.stderr, r.stderr
        assert "no round" not in r.stderr.lower(), "the refusal denies the round beside it"
        round_ = json.loads(marker_path(tmp_path).read_text())["rounds"][-1]
        assert "close" not in round_["stages"] and round_["stages"], round_["stages"]


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


class TestModeSwitch:
    """Note bae0b87b: findings handed in -> validate each; none handed in -> run
    the full pass. The mode switch is what BOUNDS the work — sprint-002's close
    re-reviewed four fix-commits with no prior findings to bound the pass."""

    def test_round_1_tells_the_reviewer_to_run_the_full_pass(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        assert sprint(repo, env, "review").returncode == 0
        # the SECTION's own words: the charter also says "run the full pass",
        # so a bare "full pass" grep passes on every bundle ever built
        assert "none — run the full pass yourself" in launches(tmp_path)[0]["stdin"]

    def test_a_second_round_carries_the_prior_findings(self, tmp_path):
        """Read from the MARKER state, which is where close.py keeps rounds.
        Reading `reports/` off disk would be a second source of truth — so the
        fixture CONSTRUCTS the marker, never the report file."""
        repo, env, _g = make_repo(tmp_path)
        path = marker_path(tmp_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "rounds": [
                        {"fixed": [], "blocking": ["ROUND-1-BLOCKER"], "noted": ["ROUND-1-NOTE"]}
                    ],
                    "shown_sha": head(repo, env),
                }
            )
        )
        assert sprint(repo, env, "review").returncode == 0
        ran = launches(tmp_path)
        assert len(ran) == 1, "a confirming delta paid for another fanout"
        bundle = ran[0]["stdin"]
        assert "ROUND-1-BLOCKER" in bundle and "ROUND-1-NOTE" in bundle
        assert DELTA in bundle
        assert "validate that each was addressed; do not re-derive the diff" in bundle
        assert "run the full pass yourself" not in bundle, "handed findings AND told to re-derive"


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
        """render_merge_body feeds the next round's bundle and the merge body both.
        Unlabelled, this round's finder candidates — which no verifier ever judged,
        because the abort came first — read there as findings a full pass confirmed.
        """
        import bookkeep

        repo, env, _g = make_repo(tmp_path)
        candidates = {"fixed": [], "blocking": ["a silent one"], "noted": []}
        committing_stub(tmp_path, "open('src.py','a').write('# edited\\n')\n", report=candidates)
        assert sprint(repo, env, "review").returncode == 2
        rounds = json.loads(marker_path(tmp_path).read_text())["rounds"]
        assert "a silent one" in (body := bookkeep.render_merge_body(rounds))
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

    def test_the_new_agent_files_frontmatter_is_funded_not_added(self):
        """Both shipped-prose caps sit at 214/300 and 1329/1365. Constraint 1 is
        mechanical here: the sprint charter's frontmatter is paid for out of
        story-reviewer.md's."""
        sys.path.insert(0, str(CLOSE.parent))
        from spawn import (
            COMPONENT_METADATA_CAP,
            PLUGIN_SHIPPED_CAP,
            component_metadata_chars,
            plugin_shipped_chars,
        )

        assert component_metadata_chars() // 4 <= COMPONENT_METADATA_CAP
        assert plugin_shipped_chars() // 4 <= PLUGIN_SHIPPED_CAP


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
