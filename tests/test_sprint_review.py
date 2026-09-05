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

    def test_prior_items_are_once_only_in_the_confirming_round_not_sprint_land(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        prior = {
            "fixed": [f"prior-fixed-{i:02}" for i in range(25)],
            "blocking": ["prior-blocking-0", "prior-blocking-1"],
            "noted": ["prior-noted-0", "prior-noted-1"],
        }
        path = marker_path(tmp_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"rounds": [prior], "shown_sha": head(repo, env)}))

        assert sprint(repo, env, "review").returncode == 0
        ran = launches(tmp_path)
        assert len(ran) == 1
        carried = section(
            ran[0]["stdin"],
            "Findings from earlier rounds",
            f"The stories in sprint {SPRINT_ID}",
        )
        items = [item for status_items in prior.values() for item in status_items]
        for item in items:
            assert carried.count(item) == 1, item
        assert "more, in full" not in carried

        landed = sprint(repo, env, "land", "--dry-run")
        assert landed.returncode == 0, landed.stderr
        assert "--body Sprint 2" in landed.stdout
        assert "Review round" not in landed.stdout
        assert all(item not in landed.stdout for item in items)
