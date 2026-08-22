"""Review-round findings pinned as tests. Split from test_close.py at sprint-004 open."""

import json
import subprocess
import sys

from close_helpers import (  # noqa: F401
    CARD,
    CLOSE,
    CONFIG,
    PLUGIN,
    REVIEWER_NAME,
    WORK,
    close,
    close_bare,
    launches,
    make_repo,
    marker,
    marker_file,
    prose,
    stub_reviewer,
)


class TestStoryReviewFindings:
    """story-008 close review, run by this story's own pipeline."""

    def test_a_comment_on_the_tests_header_cannot_silence_the_story_tier(self, tmp_path):
        """G2: the twin of the roles: bug, and this copy fails OPEN — a red tier
        is skipped and the story closes green."""
        repo, env, g = make_repo(tmp_path)
        (repo / ".xp" / "config.yml").write_text(
            "roles:\n  reviewer: claude/opus\ntests:   # fast / story / full\n  story: false\n"
        )
        g("add", "-A")
        g("commit", "-qm", "commented tests header")
        close(repo, env, "review")
        r = close(repo, env, "land")
        assert r.returncode != 0 and "tier" in (r.stderr + r.stdout).lower()
        assert "[done]" not in (tmp_path / "data" / "plan.md").read_text()

    def test_a_reviewer_that_writes_without_committing_is_also_refused(self, tmp_path):
        """G5: the `or dirtied` half was vacuous — Bash is deliberately not
        denied, so an uncommitted scratch write is the likelier defect."""
        repo, env, _g = make_repo(tmp_path)
        (tmp_path / "bin" / "claude").write_text(
            "#!/bin/sh\necho 'scratch' >> src/thing.py\nprintf '{\"result\": \"VERDICT: clean\"}'\n"
        )
        (tmp_path / "bin" / "claude").chmod(0o755)
        r = close(repo, env, "review")
        assert r.returncode == 2 and "reviewer" in r.stderr.lower()

    def test_a_dashless_card_header_does_not_poison_the_close_log(self, tmp_path):
        """G6: _log_close reimplemented card_title without its guard."""
        repo, env, _g = make_repo(tmp_path)
        plan = tmp_path / "data" / "plan.md"
        plan.write_text(plan.read_text().replace("#### story-042 — demo story", "#### story-042"))
        close(repo, env, "review")
        assert close(repo, env, "land").returncode == 0
        rec = json.loads((tmp_path / "data" / "closes.jsonl").read_text().splitlines()[-1])
        assert "####" not in rec["title"]

    def test_a_broken_plugin_install_refuses_instead_of_tracebacking(self, tmp_path):
        """G7: review.charter() read the agent file unguarded, in a module where
        nine tests assert no traceback reaches the lead."""
        r = subprocess.run(
            [
                sys.executable,
                "-c",
                f"import sys, pathlib; sys.path.insert(0, {str(CLOSE.parent)!r}); import review;"
                " review.PLUGIN_ROOT = pathlib.Path('/nonexistent'); review.charter()",
            ],
            capture_output=True,
            text=True,
        )
        assert r.returncode != 0 and "Traceback" not in r.stderr

    def test_pr_mode_records_the_real_merge_and_lands_done_on_trunk(self, tmp_path):
        """G3: pr mode is the argparse DEFAULT and the only mode a release: story
        consumer gets, and no test executed it to a merge. It recorded the story
        branch's HEAD as the merge sha — on a branch gh is about to delete — and
        committed the [done] flip onto the story branch, so trunk never learned."""
        repo, env, g = make_repo(tmp_path)
        origin = tmp_path / "origin.git"
        subprocess.run(["git", "init", "-q", "--bare", str(origin)], check=True, env=env)
        g("remote", "add", "origin", str(origin))
        g("push", "-q", "-u", "origin", "main")
        gh = tmp_path / "bin" / "gh"
        gh.write_text(
            '#!/bin/sh\ncase "$*" in *"pr merge"*) git push -q origin HEAD:main ;; esac\n'
        )
        gh.chmod(0o755)
        close(repo, env, "review")
        r = subprocess.run(
            [sys.executable, str(CLOSE), "story", "story-042", "land", "--merge-mode", "pr"],
            cwd=repo,
            env=env,
            capture_output=True,
            text=True,
        )
        assert r.returncode == 0, r.stderr + r.stdout
        rec = json.loads((tmp_path / "data" / "closes.jsonl").read_text().splitlines()[-1])
        ancestor = g("merge-base", "--is-ancestor", rec["merge_sha"], "origin/main")
        assert ancestor.returncode == 0, "recorded sha is not on trunk"
        assert "[done]" in (tmp_path / "data" / "plan.md").read_text(), "the flip never landed"


class TestStoryReviewFindings012a:
    """Blocking findings from story-012a's own close review."""

    def test_pr_mode_review_refuses_on_ORIGIN_trunk_motion(self, tmp_path):
        """B1: the new guard read the LOCAL trunk ref only. pr mode — the argparse
        default — integrates against origin, which the local ref never tracks, so a
        bare re-review still cleared land's origin guard with the reviewer seeing
        nothing new. The exact twin AC 4 claims to close, on the other axis."""
        repo, env, g = make_repo(tmp_path)
        origin = tmp_path / "origin.git"
        subprocess.run(["git", "init", "-q", "--bare", str(origin)], env=env, check=True)
        g("remote", "add", "origin", str(origin))
        g("push", "-q", "origin", "main", "story-042-branch")
        close(repo, env, "review")
        g("checkout", "-q", "main")
        (repo / "unrelated.txt").write_text("x\n")
        g("add", "-A")
        g("commit", "-qm", "landed on origin")
        old = g("rev-parse", "HEAD~1").stdout.strip()
        g("push", "-q", "origin", "main")
        g("reset", "-q", "--hard", "HEAD~1")
        g("update-ref", "refs/remotes/origin/main", old)
        g("checkout", "-q", "story-042-branch")
        r = close(repo, env, "review")
        assert r.returncode == 2, "a bare re-review re-baselined the origin guard"
        assert "git merge" in r.stderr

    def test_the_newest_round_survives_the_close_detail_bound(self, tmp_path):
        """B3: the cap kept the HEAD of the joined string, so one long early round
        silently dropped the round that actually gated the merge."""
        sys.path.insert(0, str(CLOSE.parent))
        import session_start

        # PAST the cap on purpose: at 174 chars against CLOSE_CAP 400 the while loop
        # never ran, and `kept.pop()` — dropping the NEWEST round — returned a
        # byte-identical string and passed. The fixture must construct truncation.
        record = {
            "rounds": [
                {"fixed": [f"round {i} " + "x" * 90], "blocking": [], "noted": []} for i in range(6)
            ]
            + [{"fixed": [], "blocking": ["R7-THE-BLOCKER-THAT-GATED-THE-MERGE"], "noted": []}]
        }
        detail = session_start._close_detail(record)
        assert "R7-THE-BLOCKER-THAT-GATED-THE-MERGE" in detail, "the newest round was dropped"
        assert "earlier elided" in detail, "nothing was truncated; the bound was not exercised"
        assert len(detail) <= session_start.CLOSE_CAP + 120

    def test_one_over_long_round_is_cut_to_the_round_cap(self, tmp_path):
        sys.path.insert(0, str(CLOSE.parent))
        import session_start

        detail = session_start._close_detail({"rounds": [{"fixed": ["y" * 900], "blocking": []}]})
        assert len(detail) <= session_start.ROUND_CAP + 40, "the per-round bound is gone"


class TestRoundThreeFindings:
    """Blocking findings from story-012a's third close-review round."""

    def test_trunk_motion_DURING_the_review_window_is_not_recorded_as_reviewed(self, tmp_path):
        """B1: the guard read the trunk tips before the launch and the marker re-read
        them ten minutes later, so a teammate landing during the window was recorded
        as the reviewed state and land compared equal. AC 4's defect, inside one
        review instead of across two."""
        repo, env, _g = make_repo(tmp_path)
        bin_dir = tmp_path / "bin"
        (bin_dir / "claude").write_text(
            "#!/bin/sh\n"
            "p=$(sed -n 's/^REPORT_PATH: //p')\n"
            'printf \'{"fixed": [], "blocking": [], "noted": []}\' > "$p"\n'
            "NEW=$(git commit-tree HEAD^{tree} -p main -m 'teammate landed mid-review')\n"
            "git update-ref refs/heads/main $NEW\n"
            'printf \'{"result": "clean"}\'\n'
        )
        (bin_dir / "claude").chmod(0o755)
        assert close(repo, env, "review").returncode == 0
        r = close(repo, env, "land")
        assert r.returncode == 2 and "moved" in r.stderr, "unreviewed trunk commits merged"

    def test_dry_run_review_does_not_delete_a_planted_report(self, tmp_path):
        """B3: the unlink ran before the dry-run return, so a preview destroyed the
        findings of a round that had been refused — the exact file the card's
        durability paragraph exists to keep."""
        repo, env, _g = make_repo(tmp_path)
        reports = tmp_path / "data" / "reports"
        reports.mkdir(parents=True)
        planted = reports / "story-042.round-1.json"
        planted.write_text(
            '{"fixed": ["findings from a refused round"], "blocking": [], "noted": []}'
        )
        assert close(repo, env, "review", "--dry-run").returncode == 0
        assert planted.exists(), "a pure preview deleted real findings"


class TestRoundThreeNoted:
    def test_a_json_array_report_refuses_instead_of_tracebacking(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        stub_reviewer(tmp_path, report="[1, 2, 3]")
        r = close(repo, env, "review")
        assert r.returncode == 2 and "not an object" in r.stderr
        assert "Traceback" not in r.stderr

    def test_each_round_writes_its_own_report_file(self, tmp_path):
        """The reports are the audit trail behind a merge body; a story-scoped path
        would clobber each earlier round and passed the whole suite."""
        repo, env, _g = make_repo(tmp_path)
        for i in (1, 2):
            stub_reviewer(tmp_path, report={"fixed": [f"round {i}"], "blocking": [], "noted": []})
            assert close(repo, env, "review").returncode == 0
        written = sorted(p.name for p in (tmp_path / "data" / "reports").glob("*.json"))
        assert written == ["story-042.round-1.json", "story-042.round-2.json"]

    def test_a_red_verify_does_not_ask_the_lead_to_file_records(self, tmp_path):
        repo, env, _g = make_repo(tmp_path, verify="false")
        stub_reviewer(tmp_path, report={"fixed": [], "blocking": [], "noted": ["N1: punted"]})
        close(repo, env, "review")
        r = close(repo, env, "land")
        assert r.returncode != 0
        assert "N1: punted" not in r.stdout, "filing instructions for a close that failed"
