"""story-014: the sprint close marshals its reviews.
Split from test_sprint_close.py at sprint-004 open."""

import json
import subprocess
import sys

from close_helpers import launches, stub_reviewer
from spawn_helpers import stub_codex
from sprint_helpers import (
    CLOSE,
    CONFIG,
    PLAN,
    PLUGIN,
    SPRINT_ID,
    head,
    make_repo,
    marker_path,
    sprint,
    staged_stub,
)
from test_close_salvage import FIXED
from test_sprint_review_resume import _stop_at_closer

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
        claude = tmp_path / "bin" / "claude"
        key_line = "key = os.path.basename(m.group(1).strip()).split('.')[1]\n"
        claude.write_text(
            claude.read_text().replace(
                key_line, key_line + f"os.makedirs({str(diff)!r}, exist_ok=True)\n"
            )
        )
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
        sources = (
            ("JUDGMENT", PLUGIN / "JUDGMENT.md", "VALUES"),
            ("VALUES", PLUGIN / "VALUES.md", "Constraints"),
            ("Constraints", repo / ".xp" / "constraints.md", "System context"),
        )
        for title, path, following in sources:
            assert f"## {title}\n\n{path.read_text()}\n\n## {following}\n\n" in bundle
        assert bundle.endswith(
            f"## System context\n\n{(repo / '.xp' / 'system.md').read_text()}\n\n"
        )

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


class TestUnrecordedArtifactPreservation:
    def test_a_completed_sprint_relaunch_leaves_prior_reports_salvageable(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        reports = tmp_path / "data" / "reports" / "sprint"
        reports.mkdir(parents=True, exist_ok=True)
        report = reports / f"{SPRINT_ID}.find-security.round-1.json"
        body = json.dumps({"fixed": ["prior finding"], "blocking": [], "noted": []}).encode()
        report.write_bytes(body)
        report.with_suffix(".patch").write_bytes(b"prior patch")
        staged_stub(tmp_path)

        reviewed = sprint(repo, env, "review")

        shifted = reports / f"{SPRINT_ID}.find-security.round-2.json"
        assert reviewed.returncode == 0, reviewed.stderr
        assert shifted.read_bytes() == body
        assert shifted.with_suffix(".patch").read_bytes() == b"prior patch"
        assert sprint(repo, env, "salvage").returncode == 0
        round_ = json.loads(marker_path(tmp_path).read_text())["rounds"][1]
        assert round_["fixed"] == ["prior finding"]
        assert round_["stages"] == ["find-security"]

    def test_an_unusable_sprint_report_is_set_aside_without_blocking_review(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        reports = tmp_path / "data" / "reports" / "sprint"
        reports.mkdir(parents=True, exist_ok=True)
        report = reports / f"{SPRINT_ID}.find-security.round-1.json"
        report.write_bytes(b"not json\x00")
        report.with_suffix(".patch").write_bytes(b"not a patch\x00")
        staged_stub(tmp_path)

        result = sprint(repo, env, "review")

        shifted = reports / f"{SPRINT_ID}.find-security.round-2.json"
        assert result.returncode == 0, result.stderr
        assert shifted.read_bytes() == b"not json\x00"
        assert shifted.with_suffix(".patch").read_bytes() == b"not a patch\x00"
        assert str(report) in result.stderr and str(shifted) in result.stderr

    def test_a_sprint_relaunch_that_records_no_round_leaves_prior_reports_salvageable(
        self, tmp_path
    ):
        repo, env, _g = make_repo(tmp_path)
        reports = tmp_path / "data" / "reports" / "sprint"
        reports.mkdir(parents=True, exist_ok=True)
        report = reports / f"{SPRINT_ID}.find-security.round-1.json"
        body = json.dumps(FIXED).encode()
        report.write_bytes(body)
        report.with_suffix(".patch").write_bytes(b"prior patch")
        stub_reviewer(tmp_path, report=None, exit_code=1)

        refused = sprint(repo, env, "review")

        assert refused.returncode == 2
        assert (reports / f"{SPRINT_ID}.find-security.round-2.json").read_bytes() == body
        assert sprint(repo, env, "salvage").returncode == 0
        round_ = json.loads(marker_path(tmp_path).read_text())["rounds"][0]
        assert round_["fixed"] == FIXED["fixed"]

    def test_an_unreadable_new_report_does_not_clobber_the_queued_sprint_set(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        reports = tmp_path / "data" / "reports" / "sprint"
        reports.mkdir(parents=True, exist_ok=True)
        report = reports / f"{SPRINT_ID}.find-security.round-1.json"
        prior = json.dumps(FIXED).encode()
        report.write_bytes(prior)
        stub_reviewer(tmp_path, report="{broken", exit_code=1)
        assert sprint(repo, env, "review").returncode == 2
        malformed = next(reports.glob(f"{SPRINT_ID}.*.round-1.json"))
        malformed_bytes = malformed.read_bytes()

        refused = sprint(repo, env, "salvage")

        queued = reports / f"{SPRINT_ID}.find-security.round-2.json"
        assert refused.returncode == 2 and "UNREADABLE" in refused.stderr
        assert str(queued) in refused.stderr
        assert malformed.read_bytes() == malformed_bytes
        assert queued.read_bytes() == prior

    def test_a_resumed_closer_that_writes_nothing_cannot_inherit_a_dead_ones_report(self, tmp_path):
        """A resume re-runs only the closer and skips the round-wide rotation, so the
        stale slot is the one file a leg can read back as its own output."""
        repo, env, _g = make_repo(tmp_path)
        _stop_at_closer(tmp_path)
        assert sprint(repo, env, "review").returncode == 2
        stale = tmp_path / "data" / "reports" / "sprint" / f"{SPRINT_ID}.close.round-1.json"
        stale.write_text(json.dumps({"fixed": [], "blocking": ["GHOST"], "noted": []}))

        _stop_at_closer(tmp_path)
        resumed = sprint(repo, env, "review")

        assert resumed.returncode == 2 and "wrote no report" in resumed.stderr
        assert "GHOST" not in marker_path(tmp_path).read_text()
        queued = stale.with_name(f"{SPRINT_ID}.close.round-2.json")
        assert json.loads(queued.read_text())["blocking"] == ["GHOST"]
