"""The Verify: line's gates — the credential mint and land, one rule at two depths.

Its own file rather than more of test_close_land.py, which stood at the 500-line
cap (constraint 8: extract, never trim a test to fit).
"""

import json
import pathlib

import pytest
from close import story_card
from close_free_card_cases import add_free_card, checkout_free, commit_on_free, spawn_free
from close_helpers import (
    CLEAN,
    NEW_FILE_PATCH,
    close,
    free,
    free_repo,
    launches,
    make_repo,
    marker,
    ready_marker,
    stub_reviewer,
)


class TestVerifyGate:
    def test_an_empty_verify_line_is_not_reported_as_a_missing_one(self, tmp_path):
        """Field report (Legacy): a card authored as `Verify:` with its commands
        bulleted below parses EMPTY, and land refused with "has no Verify: line"
        about a card that visibly has one — the absent-vs-present-but-unreadable
        conflation, third instance after the bootstrap label and system.md.

        The credential is RE-MINTED onto the edited text rather than the card being
        edited under it, because the drift guard fires first otherwise. That also
        models the only way this reaches land once mint refuses it: a card minted
        by a version that had no such guard.
        """
        from work import card_digest

        repo, env, _g = make_repo(tmp_path)
        assert close(repo, env, "review").returncode == 0
        plan = tmp_path / "data" / "plan.md"
        original = plan.read_text()

        def recredential(text):
            plan.write_text(text)
            card = story_card(text, "story-042")[0]
            ready_marker(tmp_path).write_text(
                json.dumps({"digest": card_digest(card), "card": card})
            )

        recredential(original.replace("Verify: true", "Verify:\n- `pytest -q`\n- `bun test`"))
        empty = close(repo, env, "land")
        assert empty.returncode != 0
        assert "same line" in empty.stderr.lower(), empty.stderr

        recredential(original.replace("Verify: true\n", ""))
        absent = close(repo, env, "land")
        assert absent.returncode != 0
        assert "no Verify:" in absent.stderr, absent.stderr
        assert "same line" not in absent.stderr.lower(), absent.stderr

    @pytest.mark.parametrize(
        ("verify", "reason"),
        [("printf injected > {path}", "shell syntax"), ("none — prose", "not runnable")],
    )
    def test_the_same_parser_refuses_before_review_and_land(self, tmp_path, verify, reason):
        from work import card_digest

        def rewrite_card(root, sentinel):
            plan = root / "data" / "plan.md"
            text = plan.read_text().replace(
                "Verify: true", f"Verify: {verify.format(path=sentinel)}"
            )
            plan.write_text(text)
            card = story_card(text, "story-042")[0]
            ready_marker(root).write_text(json.dumps({"digest": card_digest(card), "card": card}))

        review_root = tmp_path / "review"
        review_root.mkdir()
        sentinel = review_root / "shell-ran"
        repo, env, _g = make_repo(review_root)
        rewrite_card(review_root, sentinel)
        refused = close(repo, env, "review")
        assert refused.returncode == 2 and reason in refused.stderr
        assert "story-042" in refused.stderr and not sentinel.exists()
        assert launches(review_root) == [], "spent a reviewer on a refused Verify"

        land_root = tmp_path / "land"
        land_root.mkdir()
        sentinel = land_root / "shell-ran"
        repo, env, _g = make_repo(land_root)
        assert close(repo, env, "review").returncode == 0
        rewrite_card(land_root, sentinel)
        refused = close(repo, env, "land")
        assert refused.returncode == 2 and reason in refused.stderr
        assert not sentinel.exists(), "land executed the refused Verify"

    def test_verify_keeps_both_commands_in_an_and_chain(self, tmp_path):
        """A chain through a MOVE, not two touches: reading the same line as one
        ARGV — the change most likely to retire chaining — still creates both
        names, because touch takes many operands, so `touch a && touch b` greens
        against exactly the regression this test exists to catch. Only two
        commands run in order leave the source gone and the target there."""
        first, second = tmp_path / "first path", tmp_path / "second && # path"
        verify = f"touch '{first}' && mv '{first}' '{second}'"
        repo, env, _g = make_repo(tmp_path, verify=verify)
        assert close(repo, env, "review").returncode == 0
        assert second.exists() and not first.exists()
        second.unlink()
        assert close(repo, env, "land").returncode == 0
        assert not second.exists() and not first.exists()


class TestIncompletePlanReviewReachesTheLead:
    def marker(self, env):
        p = pathlib.Path(env["XP_DATA"]) / "markers" / "story-042.plan-review-incomplete"
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    def test_the_lead_and_the_reviewer_are_both_told(self, tmp_path):
        from close_helpers import launches, stub_reviewer

        repo, env, _g = make_repo(tmp_path)
        stub_reviewer(tmp_path)
        self.marker(env).write_text("story-042: plan review started against /d/draft.md")
        r = close(repo, env, "review")
        assert r.returncode == 0, r.stderr
        assert "plan review" in (r.stdout + r.stderr).lower(), r.stdout + r.stderr
        bundle = launches(tmp_path)[0]["stdin"]
        assert "plan review" in bundle.lower(), bundle[:600]

    def test_a_story_whose_review_completed_says_nothing(self, tmp_path):
        from close_helpers import launches, stub_reviewer

        repo, env, _g = make_repo(tmp_path)
        stub_reviewer(tmp_path)
        r = close(repo, env, "review")
        assert r.returncode == 0, r.stderr
        assert "did not complete" not in (r.stdout + r.stderr).lower()
        assert "did not complete" not in launches(tmp_path)[0]["stdin"].lower()


class TestReviewValidationAuthority:
    def test_a_green_report_on_a_red_tree_is_refused(self, tmp_path):

        repo, env, _g = make_repo(tmp_path, verify="false")
        r = close(repo, env, "review")
        assert r.returncode != 0, r.stdout
        assert "Verify red" in r.stderr, r.stderr
        from story_review_helpers import checkpoint

        assert checkpoint(env, "story-042")["status"] == "validation-red"
        assert close(repo, env, "land").returncode == 2

    @pytest.mark.parametrize("configured", [True, False], ids=["set", "unset"])
    def test_the_reviewed_tree_verify_never_answers_for_the_land_tier(self, tmp_path, configured):
        repo, env, g = make_repo(tmp_path)
        if not configured:
            config = repo / ".xp" / "config.yml"
            kept = [ln for ln in config.read_text().splitlines(True) if "story:" not in ln]
            config.write_text("".join(kept))
            g("commit", "-qam", "drop the story tier")
        r = close(repo, env, "review")
        assert r.returncode == 0, r.stderr
        assert "tests.story" not in r.stderr and "<tier>" not in r.stderr, r.stderr

    @pytest.mark.parametrize(("tier", "expected_calls"), [("", 0), ("EDIT-ME", 0), (None, 1)])
    def test_only_a_real_land_tier_can_reach_command_execution(
        self, monkeypatch, tier, expected_calls
    ):
        import overlap

        calls = []
        monkeypatch.setattr(overlap, "run_one", lambda *args: calls.append(args) or "")
        verdict = overlap.run_checks([["verify"]], tier)
        assert len(calls) == expected_calls
        if tier is None:
            assert verdict == ""
        else:
            assert verdict.startswith("refused: tests.story") and "Set tests.story" in verdict

    def test_a_verify_that_cannot_run_is_not_a_verify_that_failed(self):
        import overlap

        verdict = overlap.run_one("Verify", ["xp-no-such-command-036"])
        assert "could not be RUN" in verdict and "Verify red" not in verdict, verdict

    def test_red_validation_has_bound_evidence_and_blocks_land(self, tmp_path):
        repo, env, _g = make_repo(tmp_path, verify="false")
        assert close(repo, env, "review").returncode != 0
        from story_review_helpers import checkpoint

        sequence = checkpoint(env, "story-042")
        assert sequence["status"] == "validation-red"
        attempt = pathlib.Path(sequence["validation"][-1]["path"])
        evidence = json.loads((attempt / "run.json").read_text())
        assert evidence["status"] == "failed"
        assert close(repo, env, "land").returncode == 2

    def test_an_accepted_report_is_left_exactly_as_the_reviewer_wrote_it(self, tmp_path):
        from close_helpers import stub_reviewer

        repo, env, _g = make_repo(tmp_path)
        written = json.dumps(CLEAN, indent=2) + "\n"
        stub_reviewer(tmp_path, report=written)
        assert close(repo, env, "review").returncode == 0
        (report,) = (tmp_path / "data" / "reports").glob("*.json")
        assert report.read_text() == written

    def test_the_findings_of_a_refused_round_still_reach_the_lead_first(self, tmp_path):
        from close_helpers import stub_reviewer

        repo, env, _g = make_repo(tmp_path, verify="false")
        stub_reviewer(tmp_path, result="F1: the retry flag is inverted")
        r = close(repo, env, "review")
        assert r.returncode != 0
        assert "F1: the retry flag is inverted" in r.stdout, r.stdout

    def test_land_still_runs_verify_after_the_review_leg_does(self, tmp_path):
        repo, env, g = make_repo(tmp_path, verify="test -f sentinel")
        (repo / "sentinel").write_text("green at review time\n")
        g("add", "-A")
        g("commit", "-qm", "sentinel")
        assert close(repo, env, "review").returncode == 0, "review's own Verify was red"
        (repo / "sentinel").unlink()
        g("add", "-A")
        g("commit", "-qm", "the lead broke Verify after the round was recorded")
        landed = close(repo, env, "land")
        assert landed.returncode != 0, landed.stdout
        assert "Verify red" in landed.stderr, landed.stderr


class TestCommittedFixValidation:
    # green on the reviewed tree (`A = 2`), red on the tree the reviewer leaves
    VERIFY = (
        'python3 -c "from pathlib import Path; '
        "raise SystemExit('BROKEN' in Path('src/thing.py').read_text())\""
    )
    BREAKS_VERIFY = """diff --git a/src/thing.py b/src/thing.py
--- a/src/thing.py
+++ b/src/thing.py
@@ -1 +1,2 @@
 A = 2
+BROKEN = 1
"""

    def test_committed_fix_that_reds_verify_cannot_land(self, tmp_path):
        repo, env, _g = make_repo(tmp_path, verify=self.VERIFY)
        thing = repo / "src" / "thing.py"
        assert "BROKEN" not in thing.read_text(), "Verify was already red before the patch"
        stub_reviewer(tmp_path, patch=self.BREAKS_VERIFY)

        r = close(repo, env, "review")
        assert r.returncode != 0, r.stdout
        assert "Verify red" in r.stderr, r.stderr
        # BOTH halves, or the assertion above passes for the wrong reason: a patch
        # that never applied would red Verify only by failing to apply.
        assert "BROKEN" in thing.read_text(), "the reviewer's patch never reached the tree"
        from story_review_helpers import checkpoint

        assert checkpoint(env, "story-042")["status"] == "validation-red"
        assert close(repo, env, "land").returncode == 2

    def test_closer_blocker_preserves_fix_and_refuses_land(self, tmp_path):
        repo, env, g = make_repo(tmp_path, verify=self.VERIFY)
        report = {"fixed": [], "blocking": ["B"], "schema": 2, "dropped": [], "debt": []}
        stub_reviewer(tmp_path, patch=self.BREAKS_VERIFY, report=report)
        launched = g("rev-parse", "HEAD").stdout.strip()

        r = close(repo, env, "review")
        assert r.returncode != 0 and g("rev-parse", "HEAD").stdout.strip() != launched
        assert "git reset" not in r.stderr, r.stderr
        from story_review_helpers import checkpoint

        sequence = checkpoint(env, "story-042")
        assert sequence["status"] == "blocked"
        assert sequence["stages"]["closer"]["report"]["blocking"] == ["B"]
        assert close(repo, env, "land").returncode == 2

    def test_solution_blocker_is_recorded_and_returned_to_lead(self, tmp_path):
        repo, env, _g = make_repo(tmp_path, verify="false")
        stub_reviewer(
            tmp_path,
            report={"fixed": [], "blocking": ["B"], "schema": 2, "dropped": [], "debt": []},
        )

        r = close(repo, env, "review")
        assert r.returncode != 0 and "git reset --hard" not in r.stderr, r.stderr
        assert "xp.py story story-042 review" in r.stderr, r.stderr
        assert marker(tmp_path)["rounds"][-1]["blocking"] == ["B"]


class TestFreeCorrectionLands:
    def test_free_correction_lands_with_normalized_slug(self, tmp_path):
        repo, env, g = free_repo(tmp_path)
        started = free(repo, env, "Fix Typo", "start")
        assert started.returncode == 0 and "free fix-typo review" in started.stdout
        _branch, key = checkout_free(g)
        add_free_card(env, key)
        commit_on_free(repo, g)
        tree = spawn_free(repo, env, g, tmp_path, key)
        stub_reviewer(tmp_path, patch=NEW_FILE_PATCH)

        r = free(tree, env, "Fix Typo", "review")

        assert r.returncode == 0, r.stderr + r.stdout
        assert (tree / "src/fixed.py").exists()
        landed = free(tree, env, "Fix Typo", "land")
        assert landed.returncode == 0, landed.stderr


class TestFailedFixEvidenceWrite:
    def test_failed_evidence_write_keeps_committed_fix(self, tmp_path, monkeypatch):
        import review

        repo, env, g = make_repo(tmp_path)
        reviewed = g("rev-parse", "HEAD").stdout.strip()
        (repo / "reviewer-fix.txt").write_text("the reviewer's fix\n")
        g("add", "-A")
        g("commit", "-qm", "reviewer patch")
        applied = g("rev-parse", "HEAD").stdout.strip()
        assert applied != reviewed, "the fixture never moved the tree"

        report = pathlib.Path(env["XP_DATA"]) / "reports" / "story-042.round-1.json"
        report.parent.mkdir(parents=True, exist_ok=True)
        review.diff_path(report).mkdir(parents=True, exist_ok=True)
        (repo / ".git" / "index.lock").write_text("")

        monkeypatch.chdir(repo)
        refusal = review.write_reviewer_diff(report, reviewed, "story story-042")

        assert refusal.startswith("refused: "), refusal
        assert "reset --hard" not in refusal, f"a destructive undo for OUR commit:\n{refusal}"
        assert str(review.diff_path(report)) in refusal
        assert g("rev-parse", "HEAD").stdout.strip() == applied, "the patch commit was lost"
