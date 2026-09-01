"""The story reviewer launch contract, extracted for constraint 8."""

from close_helpers import LEAD_CREDS, close, launches, make_repo, marker, stub_reviewer


class TestReviewLeg:
    """The pipeline spawns the reviewer itself and records its structured report."""

    def test_review_launches_the_reviewer_with_the_bundle_inlined(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        r = close(repo, {**env, **LEAD_CREDS}, "review")
        assert r.returncode == 0, r.stderr
        (launch,) = launches(tmp_path)
        argv = launch["argv"]
        assert "--plugin-dir" in argv and "-p" in argv
        assert argv[argv.index("--model") + 1] == "opus"
        assert argv[argv.index("--output-format") + 1] == "stream-json"
        assert "--verbose" in argv
        assert "--dangerously-skip-permissions" in argv
        assert "--permission-mode" not in argv
        assert not [k for k in launch["env"] if k.startswith(("GIT_AUTHOR_", "GIT_COMMITTER_"))]
        prompt = launch["stdin"]
        assert "fault-inject" in prompt.lower()
        assert "demo story" in prompt
        assert "-A = 1" in prompt and "+A = 2" in prompt
        assert "CONSTRAINT-SENTINEL" in prompt and "SYSTEM-SENTINEL" in prompt
        assert "PATCH_PATH:" in prompt and "tree exactly as you found it" in prompt

    def test_the_spawned_reviewer_is_not_a_lead_and_cannot_close(self, tmp_path):
        """N10: this story's Verify does not run the matching spawn test."""
        repo, env, _g = make_repo(tmp_path)
        close(repo, {**env, **LEAD_CREDS}, "review")
        (launch,) = launches(tmp_path)
        assert launch["env"]["XP_ROLE"] == "reviewer"
        assert not [k for k in launch["env"] if k.startswith(("GIT_AUTHOR_", "GIT_COMMITTER_"))]

    def test_reviewer_crash_refuses_cleanly_surfacing_its_stderr(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        stub_reviewer(tmp_path, raw="not json at all", exit_code=1)
        r = close(repo, env, "review")
        assert r.returncode == 2 and "Traceback" not in r.stderr

    def test_reviewer_non_json_output_refuses_cleanly(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        stub_reviewer(tmp_path, raw="not json at all", exit_code=0)
        r = close(repo, env, "review")
        assert r.returncode == 2 and "Traceback" not in r.stderr

    def test_a_blocking_report_is_recorded_when_verify_is_red(self, tmp_path):
        repo, env, _g = make_repo(tmp_path, verify="false")
        finding = "the retry flag is inverted"
        stub_reviewer(tmp_path, report={"fixed": [], "blocking": [finding], "noted": []})
        assert close(repo, env, "review").returncode == 2
        assert marker(tmp_path)["rounds"][-1]["blocking"] == [finding]
        land = close(repo, env, "land")
        assert land.returncode == 2 and finding in land.stderr and "blocking" in land.stderr

    def test_dry_run_review_launches_nothing(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        r = close(repo, env, "review", "--dry-run")
        assert r.returncode == 0 and launches(tmp_path) == []
