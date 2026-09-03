"""The land leg: bookkeeping, failure modes, the structured gate.
Split from test_close.py at sprint-004 open."""

import json
import subprocess
import sys

import pytest
from close_helpers import (
    CLOSE,
    SPAWN,
    close,
    make_repo,
    marker,
    stub_reviewer,
)


class TestLandFailureModes:
    """Land's failure modes: partial bookkeeping and pr-mode shas."""

    def test_a_plan_that_vanished_between_review_and_land_refuses_not_tracebacks(self, tmp_path):
        """`.xp/plan.md` was git-tracked, so land's unguarded read could not miss
        it while the branch was checked out. story-019 moved the plan out of the
        repo, where nothing versions it (DESIGN §3b cost 1) — and land re-reads it
        AFTER the review leg, so an ordinary `rm` between the two legs reached the
        lead as a FileNotFoundError stack. review's own leg already refuses here;
        land is the copy that was left behind."""
        repo, env, _g = make_repo(tmp_path)
        close(repo, env, "review")
        (tmp_path / "data" / "plan.md").unlink()
        r = close(repo, env, "land")
        assert "Traceback" not in r.stderr, r.stderr
        assert r.returncode == 2 and "no plan at" in r.stderr

    def test_an_UNREADABLE_launch_marker_refuses_rather_than_reading_as_absent(self, tmp_path):
        """Land reads this file for one thing — a completed round whose Verify redded.
        A truncated one is exactly the artifact a killed process leaves, and swallowing
        it merges a story on an earlier green round while the state that would have
        refused sits unread (constraint 15). Salvage refuses on the same file."""
        repo, env, _g = make_repo(tmp_path)
        assert close(repo, env, "review").returncode == 0
        (tmp_path / "data" / "markers" / "story-042.review-launch").write_text("{not json")

        refused = close(repo, env, "land")

        assert refused.returncode == 2 and "Traceback" not in refused.stderr, refused.stderr
        assert "not readable" in refused.stderr, refused.stderr

    def test_a_card_that_vanished_between_review_and_land_refuses_before_merging(self, tmp_path):
        """The narrower half of the same failure, and the worse one: the plan is
        still there, only the CARD is gone. Everything land checks the card for —
        the [in-progress] status, the plan-review digest, the Verify line — hangs
        off finding it, so a card-shaped hole skips all three and merges."""
        repo, env, g = make_repo(tmp_path)
        close(repo, env, "review")
        plan = tmp_path / "data" / "plan.md"
        plan.write_text(plan.read_text().split("#### story-042 ")[0])
        before = g("rev-parse", "main").stdout.strip()
        r = close(repo, env, "land")
        assert "Traceback" not in r.stderr, r.stderr
        assert r.returncode == 2 and "story-042" in r.stderr
        assert g("rev-parse", "main").stdout.strip() == before, "it merged anyway"

    def test_land_discloses_the_amendment_route_reason_and_card_diff(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        plan = tmp_path / "data" / "plan.md"
        plan.write_text(plan.read_text().replace("Files: src/thing.py", "Files: src/other.py"))
        assert close(repo, env, "review").returncode == 0
        refused = close(repo, env, "land", "--dry-run")
        assert refused.returncode == 2 and "spawn.py amend story-042" in refused.stderr

        amended = subprocess.run(
            [
                sys.executable,
                str(SPAWN),
                "amend",
                "story-042",
                "--reason",
                "implementation moved to its actual file",
            ],
            cwd=repo,
            env=env,
            capture_output=True,
            text=True,
        )
        assert amended.returncode == 0, amended.stderr
        landed = close(repo, env, "land", "--dry-run")
        assert landed.returncode == 0, landed.stderr
        audit = "implementation moved to its actual file"
        assert all(
            part in landed.stdout
            for part in (audit, "-Files: src/thing.py", "+Files: src/other.py")
        )
        assert landed.stdout.index(audit) < landed.stdout.index("would run:")

    def pr_repo(self, tmp_path):
        repo, env, g = make_repo(tmp_path)
        origin = tmp_path / "origin.git"
        subprocess.run(["git", "init", "-q", "--bare", str(origin)], check=True, env=env)
        g("remote", "add", "origin", str(origin))
        g("push", "-q", "-u", "origin", "main")
        gh = tmp_path / "bin" / "gh"
        gh.write_text(
            "#!/bin/sh\n"
            'case "$*" in *"pr merge"*)\n'
            "  git checkout -q -b _pr origin/main\n"
            '  git merge -q --no-ff -m "Merge PR" story-042-branch\n'
            "  git push -q origin _pr:main\n"
            "  git checkout -q main\n"
            "  git branch -qD _pr\n"
            # server-side delete, as the real gh API does: the tracking ref is
            # deliberately left stale, because `git fetch` without --prune keeps it
            f"  git --git-dir={origin} update-ref -d refs/heads/story-042-branch\n"
            "  git branch -qD story-042-branch ;; esac\n"
        )
        gh.chmod(0o755)
        return repo, env, g

    def land_pr(self, repo, env):
        return subprocess.run(
            [sys.executable, str(CLOSE), "story", "story-042", "land", "--merge-mode", "pr"],
            cwd=repo,
            env=env,
            capture_output=True,
            text=True,
        )

    def test_pr_merge_sha_is_the_merge_not_the_story_tip(self, tmp_path):
        """F2: --is-ancestor cannot tell them apart — the story tip is an
        ancestor of the merge too, so the assertion passed against the defect."""
        repo, env, g = self.pr_repo(tmp_path)
        close(repo, env, "review")
        story_head = g("rev-parse", "HEAD").stdout.strip()
        assert self.land_pr(repo, env).returncode == 0
        rec = json.loads((tmp_path / "data" / "closes.jsonl").read_text().splitlines()[-1])
        assert rec["merge_sha"] != story_head, "recorded the story tip, not the PR merge"

    @pytest.mark.slow
    def test_pr_mode_also_deletes_the_local_story_branch(self, tmp_path):
        """F3: AC 7 was met in local mode only. gh runs FROM the story branch,
        so --delete-branch cannot remove it locally."""
        repo, env, g = self.pr_repo(tmp_path)
        close(repo, env, "review")
        assert self.land_pr(repo, env).returncode == 0
        assert "story-042-branch" not in g("branch", "--list").stdout

    def test_pr_dry_run_previews_the_steps_that_actually_run(self, tmp_path):
        """F4: the preview still printed a bare `git push` that no longer runs,
        and omitted the three post-merge steps the delta added."""
        repo, env, _g = self.pr_repo(tmp_path)
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
                "--dry-run",
            ],
            cwd=repo,
            env=env,
            capture_output=True,
            text=True,
        )
        assert r.returncode == 0
        for step in (
            "git fetch -q origin",
            "git checkout -q main",
            "git merge --ff-only origin/main",
            "git branch -d story-042-branch",
        ):
            assert step in r.stdout, f"preview omits {step!r}"
        assert "\ngit push\n" not in r.stdout, "previewed a bare push that no longer runs"

    def test_a_successful_pr_close_does_not_cry_wolf_on_exit_3(self, tmp_path):
        """R3F1: gh --delete-branch had already removed the branch, so the
        unconditional delete 'failed' and every successful pr close exited 3
        naming a command that fails again on re-run."""
        repo, env, _g = self.pr_repo(tmp_path)
        close(repo, env, "review")
        r = self.land_pr(repo, env)
        assert r.returncode == 0, f"clean close reported incomplete: {r.stderr}"
        assert "incomplete" not in r.stderr

    def test_local_dry_run_previews_the_destructive_steps_too(self, tmp_path):
        """R3F4: F4's rule was applied to the pr arm only, and local is the mode
        release: sprint forces — the un-fixed copy is the one in daily use."""
        repo, env, _g = make_repo(tmp_path, verify="printf 'a b' && true")
        close(repo, env, "review")
        r = close(repo, env, "land", "--dry-run")
        assert r.returncode == 0
        assert "would run: printf 'a b' && true\n" in r.stdout, "the preview must be RUNNABLE"
        assert "git branch -d story-042-branch" in r.stdout
        # make_repo has NO remote, and both pushes are runtime-guarded on one —
        # previewing them here is the same overstatement F4 was filed for
        assert "git push origin" not in r.stdout, "previewed pushes that never run"
        assert "trial merge" not in r.stdout, "previewed a trial merge on an unmoved trunk"

    def test_the_dry_run_preview_names_the_trial_merge_land_would_run(self, tmp_path):
        """Same rule, the step story-018 added: a preview that omits ~2min of Verify
        on a merged tree certifies a plan nobody runs."""
        repo, env, g = make_repo(tmp_path)
        close(repo, env, "review")
        g("checkout", "-q", "main")
        (repo / "unrelated.py").write_text("x = 1\n")
        g("add", "-A")
        g("commit", "-qm", "trunk moved, disjoint")
        g("checkout", "-q", "story-042-branch")
        r = close(repo, env, "land", "--dry-run")
        assert r.returncode == 0, r.stderr
        assert "trial merge with main" in r.stdout, r.stdout

    @pytest.mark.parametrize("tier", [None, "EDIT-ME"], ids=["missing", "unedited"])
    def test_story_land_refuses_a_tier_that_cannot_run(self, tmp_path, tier):
        repo, env, g = make_repo(tmp_path)
        config = repo / ".xp" / "config.yml"
        kept = [ln for ln in config.read_text().splitlines(True) if "story:" not in ln]
        if tier is not None:  # under `tests:`, not at EOF — see test_setup's twin
            kept.insert(kept.index("tests:\n") + 1, f"  story: {tier}\n")
        config.write_text("".join(kept))
        g("add", "-A")
        g("commit", "-qm", "break story tier")
        assert close(repo, env, "review").returncode == 0

        preview = close(repo, env, "land", "--dry-run")
        assert preview.returncode == 2 and "Set tests.story" in preview.stderr
        assert preview.stdout == "", "a land that refuses previewed steps it will not take"
        landed = close(repo, env, "land")
        assert landed.returncode == 2 and "Set tests.story" in landed.stderr


class TestFullReviewFindings:
    """story-008 close review, round 5 — the first review over the whole story."""

    def test_a_full_re_review_appends_rather_than_erasing_prior_rounds(self, tmp_path):
        """R5F1: the non-delta path reset verdicts while the delta path appended
        — the same rule fixed in one of its two implementations. The merge body
        then labelled the survivor 'round 1', asserting round 1 found what round
        2 found. This is the exact workflow the full_sha bug prescribes."""
        repo, env, g = make_repo(tmp_path)
        stub_reviewer(
            tmp_path, report={"fixed": [], "blocking": ["round one blocker"], "noted": []}
        )
        close(repo, env, "review")
        (repo / "src" / "thing.py").write_text("A = 7\n")
        g("add", "-A")
        g("commit", "-qm", "lead fixes the findings")
        stub_reviewer(tmp_path, report={"fixed": [], "blocking": [], "noted": ["round two note"]})
        close(repo, env, "review")
        rounds = marker(tmp_path)["rounds"]
        assert [r["blocking"] for r in rounds] == [["round one blocker"], []]
        assert close(repo, env, "land").returncode == 0
        body = g("log", "-1", "--format=%B", "main").stdout
        assert "Review round 1: 0 fixed · 1 blocking · 0 noted" in body
        assert "blocking: round one blocker" in body
        assert "Review round 2: 0 fixed · 0 blocking · 1 noted" in body
