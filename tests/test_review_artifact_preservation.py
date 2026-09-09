"""Artifact-preservation behavior shared by story and sprint review."""

import json

import pytest
from close_helpers import close, make_repo, stub_reviewer
from sprint_helpers import SPRINT_ID, sprint
from sprint_helpers import make_repo as sprint_repo
from test_close_salvage import FIXED, KILLED, dying_reviewer, report_of


class TestTheRouteThatDestroysWhatSalvageRescues:
    """The seam a story-scoped reader cannot see: salvage rescues a killed review's
    artifacts, and the resumed session's own next action routes straight past it.
    session_start's NEXT line reads [in-progress] + a FINISHED worktree and says
    run `/story-close`, whose step 2 is `close.py story <id> review` — and that
    unlinks the report and the patch before it spawns, with a clean tree being
    exactly what a reviewer killed after restoring it leaves. Issue #44's own
    suggested recovery, 'run review again', destroys the artifact it would have
    pointed at (bug 0b33b752), and nothing said so on the way past.
    """

    @pytest.mark.slow
    def test_a_relaunched_review_says_what_it_is_about_to_delete(self, tmp_path):
        repo, env, _ = make_repo(tmp_path)
        dying_reviewer(tmp_path)
        assert close(repo, env | KILLED, "review").returncode == 2
        report = report_of(tmp_path)
        patch = report.with_suffix(".patch")
        assert report.exists() and patch.exists(), "the fixture wrote no artifacts to lose"

        stub_reviewer(tmp_path)
        again = close(repo, env, "review")
        assert "salvage" in again.stderr, again.stderr
        assert str(report) in again.stderr and str(patch) in again.stderr, again.stderr

    @pytest.mark.slow
    def test_a_first_review_warns_about_nothing(self, tmp_path):
        """The pair, so the warning cannot become wallpaper printed every round:
        no launched review means no artifacts, and a line that fires either way
        is one a lead learns to skip past.
        """
        repo, env, _ = make_repo(tmp_path)
        stub_reviewer(tmp_path)
        first = close(repo, env, "review")
        assert first.returncode == 0, first.stderr
        assert "salvage" not in first.stderr, first.stderr

    @pytest.mark.slow
    def test_the_sprint_noun_says_it_too(self, tmp_path):
        """The other implementation of the same rule, and the one issue #44 actually
        hit: sprint cmd_review's leg() unlinks `<id>.<stage>.round-N.json` before it
        spawns, so a finder's completed report is thrown away by the command a lead
        runs to recover it. Fixing only the story noun would leave the field case
        exactly as it was reported.
        """
        repo, env, _g = sprint_repo(tmp_path)
        reports = tmp_path / "data" / "reports" / "sprint"
        reports.mkdir(parents=True, exist_ok=True)
        left = reports / f"{SPRINT_ID}.find-a.round-1.json"
        left.write_text(json.dumps(FIXED))
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

        assert str(left) in killed.stderr, killed.stderr
        assert f"close.py sprint {SPRINT_ID} salvage" in killed.stderr, killed.stderr
        assert "DELETES" in killed.stderr, killed.stderr

    @pytest.mark.slow
    def test_the_sprint_noun_warns_about_nothing_on_a_first_round(self, tmp_path):
        """The pair on this noun too — a line printed every round is one a lead
        stops reading, and the kill hint below it is the one that must survive."""
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

        assert "DELETES" not in killed.stderr, killed.stderr
        assert f"close.py sprint {SPRINT_ID} salvage" in killed.stderr, killed.stderr
