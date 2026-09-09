"""Artifact-preservation behavior shared by story and sprint review."""

import json

import pytest
from close_helpers import close, make_repo, stub_reviewer
from sprint_helpers import SPRINT_ID, sprint
from sprint_helpers import make_repo as sprint_repo
from test_close_salvage import FIXED, KILLED, dying_reviewer, report_of


class TestUnrecordedArtifactPreservation:
    @pytest.mark.slow
    def test_a_relaunched_story_review_sets_prior_artifacts_aside(self, tmp_path):
        repo, env, _ = make_repo(tmp_path)
        dying_reviewer(tmp_path)
        assert close(repo, env | KILLED, "review").returncode == 2
        report = report_of(tmp_path)
        patch = report.with_suffix(".patch")
        before = report.read_bytes(), patch.read_bytes()

        stub_reviewer(tmp_path)
        again = close(repo, env, "review")
        shifted = report.with_name(report.name.replace("round-1", "round-2"))
        shifted_patch = shifted.with_suffix(".patch")
        assert again.returncode == 0, again.stderr
        assert (shifted.read_bytes(), shifted_patch.read_bytes()) == before
        assert "salvage" in again.stderr, again.stderr
        assert str(report) in again.stderr and str(shifted) in again.stderr, again.stderr

    @pytest.mark.slow
    def test_a_first_review_sets_nothing_aside(self, tmp_path):
        repo, env, _ = make_repo(tmp_path)
        stub_reviewer(tmp_path)
        first = close(repo, env, "review")
        assert first.returncode == 0, first.stderr
        assert "salvage" not in first.stderr, first.stderr

    @pytest.mark.slow
    def test_a_relaunched_sprint_review_sets_prior_artifacts_aside(self, tmp_path):
        repo, env, _g = sprint_repo(tmp_path)
        reports = tmp_path / "data" / "reports" / "sprint"
        reports.mkdir(parents=True, exist_ok=True)
        left = reports / f"{SPRINT_ID}.find-security.round-1.json"
        left.write_text(json.dumps(FIXED))
        patch = left.with_suffix(".patch")
        patch.write_bytes(b"opaque patch bytes")
        before = left.read_bytes(), patch.read_bytes()
        stub = tmp_path / "bin" / "claude"
        stub.write_text(
            "#!/bin/sh\n"
            '[ "$1 $2 $3" = "plugin list --json" ] && echo '
            '\'[{"id":"xp-plugin@xp-plugin","version":"fixture",'
            '"scope":"user"}]\' && exit 0\n'
            "sleep 30\n"
        )
        stub.chmod(0o755)

        killed = sprint(repo, env | KILLED, "review")

        shifted = left.with_name(left.name.replace("round-1", "round-2"))
        shifted_patch = shifted.with_suffix(".patch")
        assert (shifted.read_bytes(), shifted_patch.read_bytes()) == before
        assert str(left) in killed.stderr, killed.stderr
        assert str(shifted) in killed.stderr, killed.stderr
        assert f"close.py sprint {SPRINT_ID} salvage" in killed.stderr, killed.stderr

    @pytest.mark.slow
    def test_a_first_sprint_review_sets_nothing_aside(self, tmp_path):
        repo, env, _g = sprint_repo(tmp_path)
        stub = tmp_path / "bin" / "claude"
        stub.write_text(
            "#!/bin/sh\n"
            '[ "$1 $2 $3" = "plugin list --json" ] && echo '
            '\'[{"id":"xp-plugin@xp-plugin","version":"fixture",'
            '"scope":"user"}]\' && exit 0\n'
            "sleep 30\n"
        )
        stub.chmod(0o755)

        killed = sprint(repo, env | KILLED, "review")

        assert "set aside" not in killed.stderr, killed.stderr
        assert f"close.py sprint {SPRINT_ID} salvage" in killed.stderr, killed.stderr
