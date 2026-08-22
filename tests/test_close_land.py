"""The land leg: bookkeeping, failure modes, the structured gate.
Split from test_close.py at sprint-004 open."""

import json
import subprocess
import sys

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
    prose,
    stub_reviewer,
)


class TestLandBookkeeping:
    """story-008 AC 3/7/8: what land does after the merge lands."""

    def with_origin(self, tmp_path, push_story_branch=True):
        repo, env, g = make_repo(tmp_path)
        origin = tmp_path / "origin.git"
        subprocess.run(["git", "init", "-q", "--bare", str(origin)], check=True, env=env)
        g("remote", "add", "origin", str(origin))
        g("push", "-q", "-u", "origin", "main")
        if push_story_branch:
            g("push", "-q", "-u", "origin", "story-042-branch")
        return repo, env, g

    def test_land_pushes_trunk_and_deletes_the_story_branch_both_sides(self, tmp_path):
        repo, env, g = self.with_origin(tmp_path)
        close(repo, env, "review")
        r = close(repo, env, "land")
        assert r.returncode == 0, r.stderr + r.stdout
        assert "story-042-branch" not in g("branch", "--list").stdout
        assert "story-042-branch" not in g("ls-remote", "--heads", "origin").stdout
        local_main = g("rev-parse", "main").stdout.strip()
        assert g("rev-parse", "origin/main").stdout.strip() == local_main

    def test_unpushed_story_branch_does_not_produce_a_spurious_failure(self, tmp_path):
        """N2b: a story closed with `spawn --in-place` never pushed its branch —
        this repo's own story-007 did exactly that."""
        repo, env, g = self.with_origin(tmp_path, push_story_branch=False)
        close(repo, env, "review")
        r = close(repo, env, "land")
        assert r.returncode == 0, r.stderr + r.stdout
        assert "story-042-branch" not in g("branch", "--list").stdout

    def test_incomplete_bookkeeping_exits_nonzero_not_zero(self, tmp_path):
        """N2a: a warning above 'closed.' is a hand-step the lead will miss."""
        repo, env, _g = self.with_origin(tmp_path)
        close(repo, env, "review")
        subprocess.run(["rm", "-rf", str(tmp_path / "origin.git")], check=True)
        r = close(repo, env, "land")
        assert r.returncode == 3, "push failure must not read as success"
        assert "git push origin main" in r.stderr
        # the merge, flip and amend all landed and merge_sha is on a ref — only a
        # failed AMEND orphans it. Withholding the record here made the close
        # unrecordable by any command, because the card already reads [done].
        rec = json.loads((tmp_path / "data" / "closes.jsonl").read_text().splitlines()[-1])
        assert rec["story"] == "story-042"
        assert not (tmp_path / "data" / "markers" / "story-042.close.json").exists()

    def test_land_clears_the_stories_test_status_markers(self, tmp_path):
        """AC 3: cleared, never greened — close.py may not forge another
        session's measurement (DESIGN §4)."""
        repo, env, _g = make_repo(tmp_path)
        d = tmp_path / "data" / "markers"
        d.mkdir(parents=True, exist_ok=True)
        stale = d / "sess-old.story-042.test-status"
        stale.write_text(json.dumps({"story": "story-042", "verify": "true", "red": True}))
        keep = d / "sess-old.story-099.test-status"
        keep.write_text(json.dumps({"story": "story-099", "verify": "true", "red": True}))
        close(repo, env, "review")
        assert close(repo, env, "land").returncode == 0
        assert not stale.exists()
        assert keep.exists(), "another story's gate state is not this close's business"

    def test_close_record_is_appended_and_names_the_real_merge_commit(self, tmp_path):
        """AC 8 + G6: a sha read before the --amend is on no ref."""
        repo, env, g = make_repo(tmp_path)
        close(repo, env, "review")
        assert close(repo, env, "land").returncode == 0
        lines = (tmp_path / "data" / "closes.jsonl").read_text().splitlines()
        assert len(lines) == 1
        rec = json.loads(lines[0])
        assert rec["story"] == "story-042" and rec["title"] == "demo story"
        assert rec["rounds"] == [{"fixed": [], "blocking": [], "noted": []}]
        assert rec["merge_sha"] == g("rev-parse", "main").stdout.strip()
        assert g("cat-file", "-t", rec["merge_sha"]).stdout.strip() == "commit"

    def test_a_second_close_appends_rather_than_overwriting(self, tmp_path):
        """N7: overwriting would be the project-global mutable marker
        constraints #10 forbids, and would lose the sprint's history."""
        repo, env, g = make_repo(tmp_path)
        close(repo, env, "review")
        close(repo, env, "land")
        plan = repo / ".xp" / "plan.md"
        plan.write_text(
            plan.read_text() + "#### story-043 — second   [in-progress]\nVerify: true\n"
        )
        g("add", "-A")
        g("commit", "-qm", "second story card")
        g("checkout", "-qb", "story-043-branch")
        (repo / "src" / "thing.py").write_text("A = 9\n")
        g("add", "-A")
        g("commit", "-qm", "second story work")
        for action in ("review", "land"):
            subprocess.run(
                [sys.executable, str(CLOSE), "story", "story-043", action, "--merge-mode", "local"],
                cwd=repo,
                env=env,
                capture_output=True,
                text=True,
            )
        records = (tmp_path / "data" / "closes.jsonl").read_text().splitlines()
        assert [json.loads(r)["story"] for r in records] == ["story-042", "story-043"]


class TestLandFailureModes:
    """Land's failure modes: partial bookkeeping, orphaned amends, pr-mode shas."""

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

    def test_a_failing_amend_hook_does_not_traceback_or_lose_the_flip(self, tmp_path):
        """F1: git() defaults check=True, and the amend re-runs the commit wall
        on a tree that just gained a merge — a hook failure raised, leaving the
        merge landed and the plan flip abandoned."""
        repo, env, _g = make_repo(tmp_path)
        close(repo, env, "review")
        hook = repo / ".git" / "hooks" / "pre-commit"
        hook.write_text("#!/bin/sh\nexit 1\n")
        hook.chmod(0o755)
        r = close(repo, env, "land")
        assert "Traceback" not in r.stderr, r.stderr
        assert r.returncode != 0, "an abandoned plan flip must not read as success"
        assert "amend" in (r.stderr + r.stdout).lower()
        assert "[done]" in (repo / ".xp" / "plan.md").read_text(), "the flip was discarded"

    def test_pr_merge_sha_is_the_merge_not_the_story_tip(self, tmp_path):
        """F2: --is-ancestor cannot tell them apart — the story tip is an
        ancestor of the merge too, so the assertion passed against the defect."""
        repo, env, g = self.pr_repo(tmp_path)
        close(repo, env, "review")
        story_head = g("rev-parse", "HEAD").stdout.strip()
        assert self.land_pr(repo, env).returncode == 0
        rec = json.loads((tmp_path / "data" / "closes.jsonl").read_text().splitlines()[-1])
        assert rec["merge_sha"] != story_head, "recorded the story tip, not the PR merge"

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

    def test_a_failed_amend_writes_no_close_record(self, tmp_path):
        """R3F2: the record is the fact layer AC 8 exists for — it must not name
        a sha that close.py's own printed remediation orphans."""
        repo, env, _g = make_repo(tmp_path)
        close(repo, env, "review")
        hook = repo / ".git" / "hooks" / "pre-commit"
        hook.write_text("#!/bin/sh\nexit 1\n")
        hook.chmod(0o755)
        assert close(repo, env, "land").returncode == 3
        assert not (tmp_path / "data" / "closes.jsonl").exists(), "recorded an incomplete close"
        assert (tmp_path / "data" / "markers" / "story-042.close.json").exists()

    def test_local_dry_run_previews_the_destructive_steps_too(self, tmp_path):
        """R3F4: F4's rule was applied to the pr arm only, and local is the mode
        release: sprint forces — the un-fixed copy is the one in daily use."""
        repo, env, _g = make_repo(tmp_path)
        close(repo, env, "review")
        r = close(repo, env, "land", "--dry-run")
        assert r.returncode == 0
        assert "git branch -d story-042-branch" in r.stdout
        # make_repo has NO remote, and both pushes are runtime-guarded on one —
        # previewing them here is the same overstatement F4 was filed for
        assert "git push origin" not in r.stdout, "previewed pushes that never run"


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


class TestStructuredGate:
    """story-012a: the report replaces the VERDICT line, and land never spawns."""

    def test_land_refuses_on_drift_naming_review_and_spawns_nothing(self, tmp_path):
        repo, env, g = make_repo(tmp_path)
        stub_reviewer(tmp_path, report=CLEAN)
        assert close(repo, env, "review").returncode == 0
        (repo / "src" / "thing.py").write_text("A = 3\n")
        g("add", "-A")
        g("commit", "-qm", "lead fix after review")
        r = close(repo, env, "land")
        assert r.returncode == 2
        assert "close.py story story-042 review" in r.stderr
        assert len(launches(tmp_path)) == 1, "land spawned the reviewer"

    def test_land_on_drift_is_idempotent(self, tmp_path):
        repo, env, g = make_repo(tmp_path)
        stub_reviewer(tmp_path, report=CLEAN)
        assert close(repo, env, "review").returncode == 0
        (repo / "src" / "thing.py").write_text("A = 3\n")
        g("add", "-A")
        g("commit", "-qm", "lead fix after review")
        first, second = close(repo, env, "land"), close(repo, env, "land")
        assert first.returncode == second.returncode == 2
        # the SAME refusal twice, not "refuses, then proceeds": land used to review
        # on the first call by construction, so a close cost two invocations minimum
        assert first.stderr == second.stderr
        assert "close.py story story-042 review" in first.stderr
        assert len(launches(tmp_path)) == 1

    def test_a_second_round_reviews_the_whole_story_diff_not_a_delta(self, tmp_path):
        repo, env, g = make_repo(tmp_path)
        stub_reviewer(tmp_path, report=CLEAN)
        close(repo, env, "review")
        (repo / "src" / "thing.py").write_text("A = 3\n")
        g("add", "-A")
        g("commit", "-qm", "more story work")
        assert close(repo, env, "review").returncode == 0
        # `-A = 1` is the trunk-side line only a merge-base..HEAD diff carries; a
        # delta (reviewed..HEAD) would show `-A = 2`. The inverse of the assertion
        # the deleted delta path used to earn.
        assert "-A = 1" in launches(tmp_path)[1]["stdin"]

    def test_review_refuses_while_trunk_is_ahead_of_the_merge_base(self, tmp_path):
        repo, env, g = make_repo(tmp_path)
        g("checkout", "-q", "main")
        (repo / "other.py").write_text("x = 1\n")
        g("add", "-A")
        g("commit", "-qm", "another story landed on trunk")
        g("checkout", "-q", "story-042-branch")
        stub_reviewer(tmp_path, report=CLEAN)
        r = close(repo, env, "review")
        assert r.returncode == 2, r.stdout
        assert "merge main" in r.stderr
        assert launches(tmp_path) == [], "opus was spent on a diff that cannot cover the merge"

    def test_shown_sha_is_head_at_the_end_of_a_clean_round(self, tmp_path):
        repo, env, g = make_repo(tmp_path)
        stub_reviewer(tmp_path, report=CLEAN)
        assert close(repo, env, "review").returncode == 0
        assert marker(tmp_path)["shown_sha"] == g("rev-parse", "HEAD").stdout.strip()

    def test_land_refuses_when_the_recorded_base_is_not_todays_merge_base(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        stub_reviewer(tmp_path, report=CLEAN)
        close(repo, env, "review")
        state = json.loads(marker_file(tmp_path).read_text())
        state["review_base"] = "0" * 40  # construct the condition; never observe it
        marker_file(tmp_path).write_text(json.dumps(state))
        r = close(repo, env, "land")
        assert r.returncode == 2 and "did not cover" in r.stderr

    def test_report_items_are_capped_at_the_write(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        stub_reviewer(
            tmp_path,
            report={"fixed": ["x" * 5000], "blocking": [], "noted": [f"n{i}" for i in range(200)]},
        )
        assert close(repo, env, "review").returncode == 0
        round1 = marker(tmp_path)["rounds"][0]
        assert len(round1["fixed"][0]) <= 400
        assert len(round1["noted"]) <= 20

    def test_a_prose_only_reviewer_is_refused_and_its_output_is_printed_first(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        stub_reviewer(
            tmp_path, result="VERDICT: clean\nthe findings I spent ten minutes on", report=None
        )
        r = close(repo, env, "review")
        assert r.returncode == 2
        assert "the findings I spent ten minutes on" in r.stdout, "a good review was destroyed"
        assert not marker_file(tmp_path).exists(), "a round was recorded without a report"

    def test_an_unparseable_report_is_refused(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        stub_reviewer(tmp_path, report="{not json at all")
        r = close(repo, env, "review")
        # name the real refusal: "exit 2" alone also greens on a stub that dies
        # because no REPORT_PATH was ever offered to it
        assert r.returncode == 2 and "not JSON" in r.stderr
        assert not marker_file(tmp_path).exists()

    def test_a_report_without_the_three_keys_is_refused(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        stub_reviewer(tmp_path, report={"findings": ["something"]})
        r = close(repo, env, "review")
        assert r.returncode == 2 and "blocking" in r.stderr, "the refusal must name what is missing"
        assert not marker_file(tmp_path).exists()

    def test_a_planted_report_cannot_certify_a_round_that_wrote_nothing(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        reports = tmp_path / "data" / "reports"
        reports.mkdir(parents=True)
        (reports / "story-042.round-1.json").write_text(
            json.dumps({"fixed": ["a fix that never happened"], "blocking": [], "noted": []})
        )
        stub_reviewer(tmp_path, report=None)
        r = close(repo, env, "review")
        assert r.returncode == 2
        assert not marker_file(tmp_path).exists(), "a stale report certified an empty round"

    def test_land_refuses_while_the_last_round_has_blocking_findings(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        stub_reviewer(
            tmp_path,
            report={"fixed": [], "blocking": ["B1: the new guard is vacuous"], "noted": []},
        )
        close(repo, env, "review")
        r = close(repo, env, "land")
        assert r.returncode == 2 and "B1: the new guard is vacuous" in r.stderr

    def test_land_prints_noted_items_for_filing(self, tmp_path):
        repo, env, g = make_repo(tmp_path)
        stub_reviewer(
            tmp_path, report={"fixed": [], "blocking": [], "noted": ["N1: this name misleads"]}
        )
        close(repo, env, "review")
        r = close(repo, env, "land")
        assert r.returncode == 0, r.stderr
        assert "N1: this name misleads" in r.stdout and "PROCESS.md" in r.stdout
        # the merge body is DESIGN §6's git-versioned audit trail: assert the ITEM,
        # not just its count — deleting "noted" from the renderer passed 192 tests
        assert "noted: N1: this name misleads" in g("log", "-1", "--format=%B", "main").stdout

    def test_three_rounds_are_labelled_by_their_true_round_number(self, tmp_path):
        repo, env, g = make_repo(tmp_path)
        for i in (1, 2, 3):
            stub_reviewer(
                tmp_path, report={"fixed": [f"round {i} fix"], "blocking": [], "noted": []}
            )
            assert close(repo, env, "review").returncode == 0
        assert close(repo, env, "land").returncode == 0
        body = g("log", "-1", "--format=%B").stdout
        for i in (1, 2, 3):
            assert f"Review round {i}" in body and f"round {i} fix" in body
