"""The review leg against sprint integration and trunk motion.
Split from test_close.py at sprint-004 open."""

import shutil
import subprocess
import sys

import pytest
from close_helpers import (
    CLOSE,
    PLUGIN,
    close,
    launches,
    make_repo,
    marker_file,
)


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
