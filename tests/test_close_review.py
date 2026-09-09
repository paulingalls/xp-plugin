"""The review leg against sprint integration and trunk motion.
Split from test_close.py at sprint-004 open."""

import json
import shutil
import subprocess
import sys

import pytest
from close_helpers import (
    CLOSE,
    FIX_PATCH,
    PLUGIN,
    close,
    launches,
    make_repo,
    marker_file,
    stub_reviewer,
)
from test_close_salvage import FIXED, salvage


class TestSprintCloseFindings:
    """sprint-001 broad review: consumer-facing correctness before release."""

    def test_start_works_from_repo_subdirectory(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        sub = repo / "src"
        r = subprocess.run(
            [sys.executable, str(CLOSE), "story", "story-042", "review", "--merge-mode", "local"],
            cwd=sub,
            env=env,
            capture_output=True,
            text=True,
        )
        assert r.returncode == 0 and "demo story" in launches(tmp_path)[0]["stdin"]

    def test_bundle_values_come_from_plugin_root(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        (repo / "VALUES.md").unlink()  # consumer repos have no VALUES.md of their own
        subprocess.run(["git", "add", "-A"], cwd=repo, env=env, capture_output=True)
        subprocess.run(["git", "commit", "-qm", "x"], cwd=repo, env=env, capture_output=True)
        r = close(repo, env, "review")
        assert r.returncode == 0
        bundle = launches(tmp_path)[0]["stdin"]
        assert "Communication" in bundle and "(missing" not in bundle
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

    def test_missing_gh_refused_before_any_push(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        close(repo, env, "review")
        r = subprocess.run(
            [
                sys.executable,
                str(CLOSE),
                "story",
                "story-042",
                "land",
                "--merge-mode",
                "pr",
            ],
            cwd=repo,
            env={**env, "PATH": "/usr/bin:/bin"},  # no gh on PATH
            capture_output=True,
            text=True,
        )
        assert r.returncode == 2 and "gh" in r.stderr and "Traceback" not in r.stderr

    def test_missing_plan_md_refused_cleanly(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        (tmp_path / "data" / "plan.md").unlink()
        r = close(repo, env, "review")
        assert r.returncode == 2 and "plan.md" in r.stderr and "Traceback" not in r.stderr

    def test_bracketless_story_header_refused_cleanly(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        plan = tmp_path / "data" / "plan.md"
        plan.write_text(plan.read_text().replace("   [in-progress]", ""))
        r = close(repo, env, "review")
        assert r.returncode == 2 and "Traceback" not in r.stderr


class TestReviewAuthority:
    @pytest.mark.parametrize("name", ["JUDGMENT.md", "VALUES.md", "constraints.md", "system.md"])
    @pytest.mark.parametrize("state", ["MISSING", "EMPTY", "UNREADABLE"])
    def test_required_input_state_refuses_before_story_launch(self, tmp_path, name, state):
        repo, env, g = make_repo(tmp_path)
        plugin = tmp_path / "plugin-copy"
        shutil.copytree(PLUGIN, plugin)
        plugin_owned = name in {"JUDGMENT.md", "VALUES.md"}
        target = plugin / name if plugin_owned else repo / ".xp" / name
        target.unlink()
        if state == "EMPTY":
            target.write_text(" \n\t")
        elif state == "UNREADABLE":
            target.mkdir()
        if not plugin_owned:
            g("add", "-A")
            assert g("commit", "-qm", f"construct {state.lower()} {name}").returncode == 0
        marker = marker_file(tmp_path)
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_bytes(b'{"rounds": []}')
        before = marker.read_bytes()

        result = close(repo, env, "review", close=plugin / "scripts" / "close.py")

        shown_path = str(target) if plugin_owned else f".xp/{name}"
        assert result.returncode == 2
        assert state in result.stderr and shown_path in result.stderr
        assert "review again" in result.stderr
        assert "Traceback" not in result.stderr
        assert launches(tmp_path) == []
        assert "(missing:" not in result.stdout + result.stderr
        assert not (tmp_path / "data" / "markers" / "story-042.review-launch").exists()
        assert marker.read_bytes() == before

    def test_a_rubric_this_user_cannot_read_is_UNREADABLE_not_a_traceback(self, tmp_path):
        """A directory raises IsADirectoryError; the state the card names is a
        permission denial, and only chmod constructs it — narrowing the handler to
        the directory alone leaves every case above green."""
        repo, env, _g = make_repo(tmp_path)
        plugin = tmp_path / "plugin-copy"
        shutil.copytree(PLUGIN, plugin)
        (plugin / "VALUES.md").chmod(0o000)

        result = close(repo, env, "review", close=plugin / "scripts" / "close.py")

        assert result.returncode == 2, result.stderr
        assert "UNREADABLE" in result.stderr and str(plugin / "VALUES.md") in result.stderr
        assert "Traceback" not in result.stderr
        assert launches(tmp_path) == []

    def test_a_rubric_that_is_not_utf8_is_named_rather_than_decoded(self, tmp_path):
        """The fourth state of a read this guard exists to enumerate, and the one
        the field has already produced: spawn.py and handback.py both name a
        `.xp/system.md` that is not UTF-8, because UnicodeDecodeError is a
        ValueError and no OSError arm catches it."""
        repo, env, _g = make_repo(tmp_path)
        plugin = tmp_path / "plugin-copy"
        shutil.copytree(PLUGIN, plugin)
        (plugin / "JUDGMENT.md").write_bytes(b"# Judgment\nred first, caf\xe9\n")

        result = close(repo, env, "review", close=plugin / "scripts" / "close.py")

        assert result.returncode == 2, result.stderr
        assert "NOT UTF-8" in result.stderr and str(plugin / "JUDGMENT.md") in result.stderr
        assert "Traceback" not in result.stderr
        assert launches(tmp_path) == []


class TestTrunkMotionGuards:
    """story-012a: trunk motion is refused at REVIEW, on both the local and the
    origin ref, because merge-base does not move when trunk advances."""

    def test_a_bare_re_review_cannot_clear_the_OVERLAP_refusal(self, tmp_path):
        """Its second claim, which outlived the guard it was written for: a refusal
        whose remediation does not work is a wall. Re-running review alone must NOT
        clear it — merge-base does not move when trunk advances, so the reviewer
        would see nothing new — and `git merge <trunk>` then review must."""
        repo, env, g = make_repo(tmp_path)
        close(repo, env, "review")
        g("checkout", "-q", "main")
        (repo / "src" / "thing.py").write_text("someone else landed a story here\n")
        g("add", "-A")
        g("commit", "-qm", "trunk moved on the story's own file")
        g("checkout", "-q", "story-042-branch")
        assert close(repo, env, "land").returncode == 2
        assert close(repo, env, "review").returncode == 0, "the review leg is not the wall"
        assert close(repo, env, "land").returncode == 2, "a bare re-review cleared the overlap"
        g("merge", "-q", "main", "-m", "merge trunk", check=False)
        (repo / "src" / "thing.py").write_text("A = 2\nsomeone else landed a story here\n")
        g("add", "-A")
        g("commit", "-qm", "resolve")
        assert close(repo, env, "review").returncode == 0
        r = close(repo, env, "land")
        assert r.returncode == 0, r.stderr
        assert "someone else landed a story here" in (repo / "src" / "thing.py").read_text()


class TestUnrecordedArtifactPreservation:
    @pytest.mark.slow
    def test_repeated_story_relaunches_leave_each_prior_round_salvageable(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        reports = tmp_path / "data" / "reports"
        saved = []
        for finding in ("newer", "older"):
            stub_reviewer(
                tmp_path,
                report={"fixed": [finding], "blocking": [], "noted": []},
                exit_code=1,
            )
            assert close(repo, env, "review").returncode == 2
            saved.append((reports / "story-042.round-1.json").read_bytes())

        stub_reviewer(tmp_path)
        assert close(repo, env, "review").returncode == 0
        assert (reports / "story-042.round-2.json").read_bytes() == saved[1]
        assert (reports / "story-042.round-3.json").read_bytes() == saved[0]
        for round_n in (2, 3):
            assert (tmp_path / "data" / "markers" / f"story-042.round-{round_n}.launch").exists()

        assert salvage(repo, env).returncode == 0
        assert salvage(repo, env).returncode == 0
        rounds = json.loads(marker_file(tmp_path).read_text())["rounds"]
        assert [round_["fixed"] for round_ in rounds] == [["newer"], ["older"], []]

    def test_salvaging_an_older_round_cannot_clear_a_later_blocking_round(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        stub_reviewer(tmp_path, report=FIXED, exit_code=1)
        assert close(repo, env, "review").returncode == 2
        blocker = {"fixed": [], "blocking": ["LIVE-BLOCKER"], "noted": []}
        stub_reviewer(tmp_path, report=blocker)
        assert close(repo, env, "review").returncode == 0

        rescued = salvage(repo, env)

        assert rescued.returncode == 0, rescued.stderr
        rounds = json.loads(marker_file(tmp_path).read_text())["rounds"]
        assert [round_["blocking"] for round_ in rounds] == [[], ["LIVE-BLOCKER"]]
        landed = close(repo, env, "land")
        assert landed.returncode == 2 and "LIVE-BLOCKER" in landed.stderr

    def test_a_later_review_patch_does_not_rewrite_an_older_launch_tree(self, tmp_path):
        repo, env, g = make_repo(tmp_path)
        launched = g("rev-parse", "HEAD").stdout.strip()
        stub_reviewer(tmp_path, report=FIXED, exit_code=1)
        assert close(repo, env, "review").returncode == 2
        stub_reviewer(tmp_path, patch=FIX_PATCH)
        assert close(repo, env, "review").returncode == 0

        sidecar = tmp_path / "data" / "markers" / "story-042.round-2.launch"
        assert json.loads(sidecar.read_text())["head"] == launched
        refused = salvage(repo, env)
        assert refused.returncode == 2 and "HEAD is no longer" in refused.stderr

    def test_story_queue_never_pairs_a_report_with_another_attempts_patch(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        stub_reviewer(tmp_path, report=None, patch=FIX_PATCH, exit_code=1)
        assert close(repo, env, "review").returncode == 2
        second = {"fixed": ["second attempt"], "blocking": [], "noted": []}
        stub_reviewer(tmp_path, report=second, patch=None, exit_code=1)
        assert close(repo, env, "review").returncode == 2
        stub_reviewer(tmp_path)
        assert close(repo, env, "review").returncode == 0

        rescued = salvage(repo, env)

        assert rescued.returncode == 0, rescued.stderr
        assert "x = 1" not in (repo / "src" / "thing.py").read_text()
        rounds = json.loads(marker_file(tmp_path).read_text())["rounds"]
        assert [round_["fixed"] for round_ in rounds] == [["second attempt"], []]
        orphan = salvage(repo, env)
        assert orphan.returncode == 2 and "belongs to no tree" in orphan.stderr
        assert "story-042.round-3.patch" in orphan.stderr

    def test_an_unusable_story_report_is_set_aside_without_blocking_review(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        report = tmp_path / "data" / "reports" / "story-042.round-1.json"
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_bytes(b"not json\x00")
        report.with_suffix(".patch").write_bytes(b"not a patch\x00")

        result = close(repo, env, "review")

        shifted = report.with_name("story-042.round-2.json")
        assert result.returncode == 0, result.stderr
        assert shifted.read_bytes() == b"not json\x00"
        assert shifted.with_suffix(".patch").read_bytes() == b"not a patch\x00"
        assert str(report) in result.stderr and str(shifted) in result.stderr

    def test_a_missing_report_does_not_queue_an_orphan_launch(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        stub_reviewer(tmp_path, report=None, patch="opaque", exit_code=1)
        assert close(repo, env, "review").returncode == 2

        stub_reviewer(tmp_path)
        assert close(repo, env, "review").returncode == 0

        reports = tmp_path / "data" / "reports"
        assert (reports / "story-042.round-2.patch").read_bytes() == b"opaque"
        assert not (tmp_path / "data" / "markers" / "story-042.round-2.launch").exists()

    @pytest.mark.slow
    def test_a_bundle_refusal_preserves_the_unrecorded_story_artifacts(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        saved = []
        for finding in ("first", "second"):
            stub_reviewer(
                tmp_path,
                report={"fixed": [finding], "blocking": [], "noted": []},
                exit_code=1,
            )
            assert close(repo, env, "review").returncode == 2
            saved.append((tmp_path / "data" / "reports" / "story-042.round-1.json").read_bytes())

        plugin = tmp_path / "plugin-copy"
        shutil.copytree(PLUGIN, plugin)
        (plugin / "JUDGMENT.md").unlink()
        refused = close(repo, env, "review", close=plugin / "scripts" / "close.py")
        assert refused.returncode == 2 and "MISSING" in refused.stderr
        reports = tmp_path / "data" / "reports"
        assert (reports / "story-042.round-2.json").read_bytes() == saved[1]
        assert (reports / "story-042.round-3.json").read_bytes() == saved[0]

        assert salvage(repo, env).returncode == 0
        assert (reports / "story-042.round-2.json").exists()
        assert salvage(repo, env).returncode == 0
        rounds = json.loads(marker_file(tmp_path).read_text())["rounds"]
        assert [round_["fixed"] for round_ in rounds] == [["first"], ["second"]]

    def test_a_queued_story_checkpoint_is_not_advanced_across_unrelated_motion(self, tmp_path):
        repo, env, g = make_repo(tmp_path)
        stub_reviewer(tmp_path, report=FIXED, exit_code=1)
        assert close(repo, env, "review").returncode == 2
        (repo / "src" / "other.py").write_text("lead = True\n")
        g("add", "-A")
        g("commit", "-qm", "lead motion")
        stub_reviewer(tmp_path)
        assert close(repo, env, "review").returncode == 0

        refused = salvage(repo, env)

        assert refused.returncode == 2
        assert "close marker changed" in refused.stderr or "HEAD is no longer" in refused.stderr
        assert (tmp_path / "data" / "reports" / "story-042.round-2.json").exists()

    def test_queued_salvage_refuses_marker_motion_after_replacement(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        stub_reviewer(tmp_path, report=FIXED, exit_code=1)
        assert close(repo, env, "review").returncode == 2
        stub_reviewer(tmp_path)
        assert close(repo, env, "review").returncode == 0
        marker = marker_file(tmp_path)
        state = json.loads(marker.read_text())
        marker.write_text(json.dumps(state | {"tampered": True}))

        refused = salvage(repo, env)

        assert refused.returncode == 2 and "close marker changed" in refused.stderr
        assert (tmp_path / "data" / "markers" / "story-042.round-2.launch").exists()

    def test_marker_motion_still_refuses_an_ordinary_killed_review(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        stub_reviewer(tmp_path, report=FIXED, exit_code=1)
        assert close(repo, env, "review").returncode == 2
        marker_file(tmp_path).write_text(json.dumps({"rounds": []}))

        refused = salvage(repo, env)

        assert refused.returncode == 2 and "close marker changed" in refused.stderr
        assert json.loads(marker_file(tmp_path).read_text())["rounds"] == []

    def test_a_verify_red_queued_salvage_rewrites_only_its_sidecar(self, tmp_path):
        sentinel = tmp_path / "verify-green"
        sentinel.write_text("green")
        repo, env, _g = make_repo(tmp_path, verify=f"test -e {sentinel}")
        stub_reviewer(tmp_path, report=FIXED, patch=FIX_PATCH, exit_code=1)
        assert close(repo, env, "review").returncode == 2
        stub_reviewer(tmp_path)
        assert close(repo, env, "review").returncode == 0
        sentinel.unlink()

        refused = salvage(repo, env)

        sidecar = tmp_path / "data" / "markers" / "story-042.round-2.launch"
        canonical = tmp_path / "data" / "markers" / "story-042.review-launch"
        assert refused.returncode == 2 and "Verify red" in refused.stderr
        assert "verify_red" in json.loads(sidecar.read_text())
        assert not canonical.exists()
        sentinel.write_text("green")
        landed = close(repo, env, "land")
        assert landed.returncode == 2 and "review completed" in landed.stderr
