"""The review leg against sprint integration, trunk motion and self-close.
Split from test_close.py at sprint-004 open."""

import json
import subprocess
import sys
from itertools import pairwise

import pytest
from close_helpers import (  # noqa: F401
    CARD,
    CLEAN,
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
    mint_ready,
    prose,
    stub_reviewer,
)
from spawn_helpers import stub_codex


class TestSprintIntegration:
    """story-005: release: sprint — stories integrate on the sprint branch."""

    def sprint_repo(self, tmp_path):
        repo, env, g = make_repo(tmp_path)
        (repo / ".xp" / "config.yml").write_text(
            "release: sprint\nsprint_branch: sprint-001\n" + CONFIG
        )
        g("checkout", "-q", "main")
        g("add", "-A")
        g("commit", "-qm", "sprint config")
        # real mid-sprint shape: sprint-001 has DIVERGED from main before the story
        g("checkout", "-qb", "sprint-001")
        (repo / "sprint-work.txt").write_text("earlier story landed here\n")
        g("add", "-A")
        g("commit", "-qm", "earlier sprint story")
        # story branches off the sprint branch, not main
        g("branch", "-D", "story-042-branch")
        g("checkout", "-qb", "story-042-branch")
        (repo / "src" / "thing.py").write_text("A = 2\n")
        g("add", "-A")
        g("commit", "-qm", "story work")
        return repo, env, g

    def test_close_merges_into_sprint_branch_not_main(self, tmp_path):
        repo, env, g = self.sprint_repo(tmp_path)
        r = close(repo, env, "review")
        # bundle diff is story-only: already-landed sprint work must not appear (B1)
        assert "earlier story landed here" not in r.stdout
        r = close(repo, env, "land")
        assert r.returncode == 0, r.stderr
        assert "Review round 1" in g("log", "sprint-001", "-1", "--format=%B").stdout
        assert "[done]" in (tmp_path / "data" / "plan.md").read_text()
        assert "Review round" not in g("log", "main", "--format=%B").stdout  # main untouched

    def test_sprint_release_without_branch_key_falls_back_to_default(self, tmp_path):
        repo, env, g = make_repo(tmp_path)
        (repo / ".xp" / "config.yml").write_text("release: sprint\n" + CONFIG)
        g("add", "-A")
        g("commit", "-qm", "sprint release, no branch yet")
        close(repo, env, "review")
        r = close(repo, env, "land")
        assert r.returncode == 0, r.stderr
        assert "Review round 1" in g("log", "main", "-1", "--format=%B").stdout

    def test_story_release_ignores_sprint_branch_key(self, tmp_path):
        repo, env, g = make_repo(tmp_path)
        (repo / ".xp" / "config.yml").write_text(
            "release: story\nsprint_branch: sprint-001\n" + CONFIG
        )
        g("branch", "sprint-001", "main")
        g("add", "-A")
        g("commit", "-qm", "story release")
        close(repo, env, "review")
        r = close(repo, env, "land")
        assert r.returncode == 0, r.stderr
        assert "Review round 1" in g("log", "main", "-1", "--format=%B").stdout

    def test_guards_watch_sprint_branch_not_main(self, tmp_path):
        repo, env, g = self.sprint_repo(tmp_path)
        close(repo, env, "review")
        g("checkout", "-q", "sprint-001")
        (repo / "src" / "thing.py").write_text("A = 9\n")
        g("add", "-A")
        g("commit", "-qm", "another story landed on the sprint branch")
        g("checkout", "-q", "story-042-branch")
        r = close(repo, env, "land")
        assert r.returncode == 2 and "sprint-001" in r.stderr and "src/thing.py" in r.stderr

    def test_main_motion_does_not_block_sprint_close(self, tmp_path):
        repo, env, g = self.sprint_repo(tmp_path)
        close(repo, env, "review")
        g("checkout", "-q", "main")
        (repo / "main-file.txt").write_text("x\n")
        g("add", "-A")
        g("commit", "-qm", "main moved — sprint close's concern, not ours")
        g("checkout", "-q", "story-042-branch")
        r = close(repo, env, "land")
        assert r.returncode == 0, r.stderr

    def test_the_documented_invocation_works_on_a_sprint_branch(self, tmp_path):
        """Broad review B2: `merge-mode` appears in NO shipped prose, and the
        documented `close.py story <id> land` defaulted to pr — which cmd_land
        refuses whenever the integration target is not the default branch. So the
        invocation the skill tells a consuming project to run was the one that
        refuses. The mode is derived now."""
        repo, env, g = self.sprint_repo(tmp_path)
        stub_reviewer(tmp_path, report=CLEAN)
        assert close_bare(repo, env, "review").returncode == 0
        r = close_bare(repo, env, "land")
        assert r.returncode == 0, r.stderr
        assert "Review round 1" in g("log", "sprint-001", "-1", "--format=%B").stdout

    def test_pr_mode_with_sprint_target_refused(self, tmp_path):
        repo, env, _g = self.sprint_repo(tmp_path)
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
            env=env,
            capture_output=True,
            text=True,
        )
        assert r.returncode == 2 and "local" in r.stderr

    def test_start_from_default_branch_still_refused(self, tmp_path):
        repo, env, g = self.sprint_repo(tmp_path)
        g("checkout", "-q", "main")
        r = close(repo, env, "review")
        assert r.returncode == 2

    def test_configured_sprint_branch_missing_refused(self, tmp_path):
        repo, env, g = make_repo(tmp_path)
        (repo / ".xp" / "config.yml").write_text(
            "release: sprint\nsprint_branch: sprint-001\n" + CONFIG
        )
        g("add", "-A")
        g("commit", "-qm", "config names a branch that does not exist")
        r = close(repo, env, "review")
        assert r.returncode == 2 and "sprint-001" in r.stderr  # fail-safe, never fall back to main

    def test_tag_named_like_sprint_branch_cannot_freeze_the_guard(self, tmp_path):
        repo, env, g = self.sprint_repo(tmp_path)
        g("tag", "sprint-001", "main")  # refs/tags wins plain rev-parse; guard must not care
        close(repo, env, "review")
        g("checkout", "-q", "sprint-001")
        (repo / "src" / "thing.py").write_text("A = 9\n")
        g("add", "-A")
        g("commit", "-qm", "another story landed on the sprint branch")
        g("checkout", "-q", "story-042-branch")
        r = close(repo, env, "land")
        assert r.returncode == 2 and "src/thing.py" in r.stderr

    def test_pr_refusal_precedes_moved_check(self, tmp_path):
        repo, env, g = self.sprint_repo(tmp_path)
        origin = tmp_path / "origin.git"
        subprocess.run(["git", "init", "-q", "--bare", str(origin)], env=env, check=True)
        g("remote", "add", "origin", str(origin))
        g("push", "-q", "origin", "sprint-001")
        close(repo, env, "review")
        g("checkout", "-q", "sprint-001")
        (repo / "src" / "thing.py").write_text("A = 9\n")  # overlapping: the costly check
        g("add", "-A")
        g("commit", "-qm", "moved")
        g("push", "-q", "origin", "sprint-001")  # origin's sprint branch moves too
        g("checkout", "-q", "story-042-branch")
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
            env=env,
            capture_output=True,
            text=True,
        )
        assert r.returncode == 2 and "local" in r.stderr and "src/thing.py" not in r.stderr


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


class TestReviewLeg:
    """The pipeline spawns the reviewer itself and records its structured report."""

    def test_review_launches_the_reviewer_with_the_bundle_inlined(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        r = close(repo, env, "review")
        assert r.returncode == 0, r.stderr
        (launch,) = launches(tmp_path)
        argv = launch["argv"]
        assert "--plugin-dir" in argv and "-p" in argv
        assert argv[argv.index("--model") + 1] == "opus"
        assert argv[argv.index("--output-format") + 1] == "stream-json"
        assert "--verbose" in argv
        assert "--dangerously-skip-permissions" not in argv
        assert ("--permission-mode", "acceptEdits") in list(pairwise(argv))
        assert not [k for k in launch["env"] if k.startswith(("GIT_AUTHOR_", "GIT_COMMITTER_"))]
        prompt = launch["stdin"]
        assert "fault-inject" in prompt.lower()  # the charter, inlined
        assert "demo story" in prompt  # the card
        assert "-A = 1" in prompt and "+A = 2" in prompt  # the cumulative diff
        assert "CONSTRAINT-SENTINEL" in prompt and "SYSTEM-SENTINEL" in prompt
        assert "PATCH_PATH:" in prompt and "leave the tree unchanged" in prompt

    def test_the_spawned_reviewer_is_not_a_lead_and_cannot_close(self, tmp_path):
        """N10: the only thing pinning the reviewer's role otherwise lives in
        test_spawn.py, which this story's Verify does not run."""
        repo, env, _g = make_repo(tmp_path)
        close(repo, env, "review")
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

    def test_dry_run_review_launches_nothing(self, tmp_path):
        """N4: --dry-run is on the shared parser; silently spawning a real opus
        session on a dry run is an expensive surprise."""
        repo, env, _g = make_repo(tmp_path)
        r = close(repo, env, "review", "--dry-run")
        assert r.returncode == 0 and launches(tmp_path) == []


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


class TestAReviewerMayNotREWRITEWhatItWasGiven:
    """012b handback N2, carried by story-011 and still open: every motion check
    is ancestry-BLIND. A reviewer that resets past reviewed_head and re-commits
    leaves `reviewed_head..HEAD` holding only its own commits, so authorship
    passes; the tree is clean, `.xp/` is untouched, the marker is intact; and
    land's own ancestor check reads shown_sha, which was recorded AFTER the
    reviewer and is therefore an ancestor of its own rewrite by construction.
    The lead's story commits merge as if reviewed, having been deleted.
    """

    def rewriting_stub(self, tmp_path):
        (tmp_path / "bin" / "claude").write_text(
            "#!/bin/sh\n"
            "p=$(sed -n 's/^REPORT_PATH: //p')\n"
            'printf \'{"fixed": [], "blocking": [], "noted": []}\' > "$p"\n'
            "git reset -q --hard HEAD~1\n"  # the lead's story work, gone
            "echo 'x = 1' > src/thing.py\n"
            "git -c user.name='xp story-reviewer' -c user.email='r@xp'"
            " commit -qam 'reviewer rewrote the branch'\n"
            'printf \'{"type": "result", "result": "clean"}\'\n'
        )
        (tmp_path / "bin" / "claude").chmod(0o755)

    def test_a_reviewer_that_rewrote_history_is_refused_and_records_nothing(self, tmp_path):
        repo, env, g = make_repo(tmp_path)
        reviewed = g("rev-parse", "HEAD").stdout.strip()
        self.rewriting_stub(tmp_path)
        r = close(repo, env, "review")
        assert r.returncode == 2, r.stdout
        assert reviewed[:8] in r.stderr and "reset --hard" in r.stderr, r.stderr
        assert not marker_file(tmp_path).exists(), "recorded a round over dropped commits"
        # and the recovery it names actually restores the lead's work
        g("reset", "-q", "--hard", reviewed)
        assert "A = 2" in (repo / "src" / "thing.py").read_text()

    @pytest.mark.slow
    def test_a_read_only_reviewer_that_adds_a_commit_is_refused(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        (tmp_path / "bin" / "claude").write_text(
            "#!/bin/sh\n"
            "p=$(sed -n 's/^REPORT_PATH: //p')\n"
            'printf \'{"fixed": ["f"], "blocking": [], "noted": []}\' > "$p"\n'
            "echo 'x = 1' >> src/thing.py\n"
            "git -c user.name='xp story-reviewer' -c user.email='r@xp' commit -qam 'fix'\n"
            'printf \'{"type": "result", "result": "fixed"}\'\n'
        )
        (tmp_path / "bin" / "claude").chmod(0o755)
        assert close(repo, env, "review").returncode == 2
        assert not marker_file(tmp_path).exists()


class TestSelfCloseRefusal:
    """story-008 AC 6: the hard property behind TEAMMATE.md's declaration."""

    def test_non_lead_roles_are_refused(self, tmp_path):
        """N3: parametrized, or this fault-injects the AC and not the widening."""
        for role in ("teammate", "reviewer", "sprint-close", ""):
            repo, env, _g = make_repo(tmp_path / f"r-{role or 'empty'}")
            r = close(repo, {**env, "XP_ROLE": role}, "review")
            assert r.returncode == 2, f"XP_ROLE={role!r} was allowed to close"
            assert "close" in r.stderr.lower()

    def test_the_lead_passes_the_same_guard(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        assert close(repo, {**env, "XP_ROLE": "lead"}, "review").returncode == 0


class TestCodexReviewerLeg:
    """story-021: the reviewer is harness-agnostic. Its report is read from the
    SAME round path with the SAME parse, so no caller of review.py can tell which
    harness wrote it — the divergence is the argv and nothing else."""

    def codex_repo(self, tmp_path, **kw):
        repo, env, g = make_repo(tmp_path)
        # network=False is the other half of story-026's AC: the flag that lets an
        # executor nest a plan review must not widen the leg that nests nothing.
        rec = stub_codex(tmp_path, commit=False, report=CLEAN, network=False, **kw)
        (repo / ".xp" / "config.yml").write_text(
            "roles:\n  reviewer: codex/gpt-5.6-terra/high\ntests:\n  story: true\n"
        )
        g("add", "-A")
        g("commit", "-qm", "reviewer role is codex")
        return repo, env, rec

    def test_the_round_is_recorded_from_a_codex_written_report(self, tmp_path):
        repo, env, _rec = self.codex_repo(tmp_path)
        r = close(repo, env, "review")
        assert r.returncode == 0, r.stderr + r.stdout
        rounds = marker(tmp_path)["rounds"]
        assert rounds == [CLEAN], rounds

    def test_the_reviewer_argv_is_the_hardened_one(self, tmp_path):
        """Not a second spawn path: the reviewer leg takes the same hardening the
        teammate leg does — the sandbox, the environment pins and the model."""
        repo, env, rec = self.codex_repo(tmp_path)
        assert close(repo, env, "review").returncode == 0
        launch = json.loads(rec.read_text())
        argv = launch["argv"]
        assert ("--sandbox", "workspace-write") in list(pairwise(argv)), argv
        assert ("--disable", "unified_exec") not in list(pairwise(argv)), argv
        assert argv[argv.index("-m") + 1] == "gpt-5.6-terra"
        assert ("-c", "model_reasoning_effort=high") in list(pairwise(argv))
        assert launch["env"]["XP_ROLE"] == "reviewer"
        assert "REPORT_PATH:" in launch["stdin"] and "demo story" in launch["stdin"]

    def test_codex_absent_from_path_refuses_without_a_traceback(self, tmp_path):
        repo, env, _rec = self.codex_repo(tmp_path)
        (tmp_path / "bin" / "codex").unlink()
        r = close(repo, env, "review")
        assert r.returncode == 2 and "Traceback" not in r.stderr, r.stderr
        assert "codex" in r.stderr and "install" in r.stderr.lower(), r.stderr


class TestTheCardsReviewerLine:
    """story-026: the config's reviewer is global, so it cannot say "author codex,
    review claude" on one story and the inverse on the next. The card line is the
    `Executor:` line's twin, and the round path and parse are unchanged."""

    def test_the_card_line_beats_the_config_default(self, tmp_path):
        repo, env, g = make_repo(tmp_path)
        (repo / ".xp" / "config.yml").write_text(
            "roles:\n  reviewer: codex/gpt-5.6-terra/high\ntests:\n  story: true\n"
        )
        g("add", "-A")
        g("commit", "-qm", "reviewer role is codex")
        plan = tmp_path / "data" / "plan.md"
        plan.write_text(
            plan.read_text().replace("Verify: true", "Verify: true\nReviewer: claude/opus")
        )
        mint_ready(repo, env)
        # nothing named codex is on PATH: config's default would refuse loudly
        # rather than pass this by accident
        r = close(repo, env, "review")
        assert r.returncode == 0, r.stdout + r.stderr
        (launch,) = launches(tmp_path)
        assert launch["argv"][launch["argv"].index("--model") + 1] == "opus"
        assert marker(tmp_path)["rounds"] == [CLEAN]
