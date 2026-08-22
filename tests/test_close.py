"""story-002 + successors: the story-close pipeline's start and review legs.
Verify: pytest -q tests/test_close.py"""

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


class TestStart:
    def test_dirty_tree_refused_naming_reason(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        (repo / "src" / "thing.py").write_text("A = 3\n")
        r = close(repo, env, "review")
        assert r.returncode == 2 and "dirty" in r.stderr.lower()

    def test_ready_story_refused(self, tmp_path):
        repo, env, _g = make_repo(tmp_path, status="ready")
        r = close(repo, env, "review")
        assert r.returncode == 2 and "in-progress" in r.stderr

    def test_a_card_ends_at_the_next_heading_of_any_level(self):
        """A card followed by a `### Sprint N` heading swallowed that sprint's
        whole preamble — story-017's card carried 55 lines of Sprint 4 planning
        prose, inlined at spawn as 'the whole scope' and charged against the
        teammate budget (bug 9ad0180b)."""
        sys.path.insert(0, str(CLOSE.parent))
        from close import story_card

        plan = CARD.format(status="ready", verify="true") + "\n### Sprint 2\nNEXT-SPRINT-PREAMBLE\n"
        card, status = story_card(plan, "story-042")
        assert status == "ready"
        assert "Verify: true" in card
        assert "NEXT-SPRINT-PREAMBLE" not in card, "the card swallowed the next section"

    def test_the_story_bundle_diffs_against_the_INTEGRATION_TARGET(self, tmp_path):
        """Bug 66272ab4: /story-close bundled `main...HEAD`, so under
        `release: sprint` every earlier story already integrated on the sprint
        branch rode into this story's review. Its filed falsifier greps SKILL.md
        for the absence of a token, which constraint 11 forbids — it greens on a
        rewording while the defect returns.

        The earlier story lives on the SPRINT BRANCH ONLY, never on main: that is
        what makes the two bases differ, and a first version of this test put it
        on both and passed against the injected bug."""
        repo, env, g = make_repo(tmp_path)
        g("checkout", "-qb", "sprint-001", "main")
        (repo / "earlier_story.py").write_text("EARLIER_STORY_SENTINEL = 1\n")
        (repo / ".xp" / "config.yml").write_text(
            CONFIG + "\nrelease: sprint\nsprint_branch: sprint-001\n"
        )
        g("add", "-A")
        g("commit", "-qm", "an earlier story, integrated on the sprint branch")
        g("checkout", "-q", "story-042-branch")
        g("merge", "-q", "--no-edit", "sprint-001")
        assert close(repo, env, "review").returncode == 0
        bundle = launches(tmp_path)[0]["stdin"]
        assert "EARLIER_STORY_SENTINEL" not in bundle, (
            "the bundle diffed against the default branch, so an already-integrated"
            " story rode into this story's review"
        )

    def test_bundle_inlines_rules_diff_card_and_work_entries(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        subprocess.run(
            [sys.executable, str(WORK), "note", "filed-during-story"],
            cwd=repo,
            env=env,
            check=True,
            capture_output=True,
        )
        r = close(repo, env, "review")
        assert r.returncode == 0, r.stderr
        bundle = launches(tmp_path)[0]["stdin"]  # the bundle is the reviewer's prompt now
        for sentinel in (
            "Communication",  # VALUES now come from the plugin root, not the repo
            "CONSTRAINT-SENTINEL",
            "SYSTEM-SENTINEL",
            "A = 2",
            "demo story",
            "filed-during-story",
        ):
            assert sentinel in bundle, f"bundle missing {sentinel}"


class TestReviewed:
    def test_verdict_flag_is_gone_so_no_verdict_can_be_hand_supplied(self, tmp_path):
        """AC 1: a lead-supplied verdict is the forgeable-verdict gap this story closes."""
        repo, env, _g = make_repo(tmp_path)
        close(repo, env, "review")
        r = close(repo, env, "land", "--verdict", "VERDICT: clean")
        assert r.returncode != 0 and "unrecognized arguments: --verdict" in r.stderr

    def test_red_verify_aborts_before_merge_naming_command(self, tmp_path):
        repo, env, g = make_repo(tmp_path, verify="false")
        close(repo, env, "review")
        r = close(repo, env, "land")
        assert r.returncode != 0 and "false" in (r.stderr + r.stdout)
        assert g("log", "main", "--oneline").stdout.count("\n") == 1  # no merge

    def test_green_close_merges_with_verdict_and_flips_status(self, tmp_path):
        repo, env, g = make_repo(tmp_path)
        close(repo, env, "review")
        r = close(repo, env, "land")
        assert r.returncode == 0, r.stderr
        body = g("log", "main", "-1", "--format=%B").stdout
        assert "Review round 1" in body
        assert "[done]" in (tmp_path / "data" / "plan.md").read_text()

    def test_conflicting_main_aborts_back_to_reviewing(self, tmp_path):
        repo, env, g = make_repo(tmp_path)
        close(repo, env, "review")
        g("checkout", "-q", "main")
        (repo / "src" / "thing.py").write_text("A = 9\n")
        g("add", "-A")
        g("commit", "-qm", "conflicting")
        g("checkout", "-q", "story-042-branch")
        # land refuses on the trunk motion, and review sends the lead to merge trunk
        # in — which is where the conflict now surfaces: on the story branch, in the
        # lead's own working tree, before any review is spent on it
        assert close(repo, env, "land").returncode == 2
        assert "git merge main" in close(repo, env, "review").stderr
        assert g("merge", "main").returncode != 0
        g("merge", "--abort")
        assert "[done]" not in (tmp_path / "data" / "plan.md").read_text()

    def test_pr_mode_dry_run_pins_gh_args(self, tmp_path):
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
                "--dry-run",
            ],
            cwd=repo,
            env=env,
            capture_output=True,
            text=True,
        )
        assert "gh pr create" in r.stdout and "Review round 1" in r.stdout
        merge_lines = [ln for ln in r.stdout.splitlines() if "gh pr merge" in ln]
        assert len(merge_lines) == 1
        assert "--merge" in merge_lines[0] and "--delete-branch" in merge_lines[0]
        assert "Review round 1" in merge_lines[0]  # rounds ride the merge, not only create
        assert any(ln.startswith("git push") for ln in r.stdout.splitlines())

    def test_reviewed_dirty_tree_refused(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        close(repo, env, "review")
        (repo / "fixed.txt").write_text("untracked dirt\n")
        r = close(repo, env, "land")
        assert r.returncode == 2 and "dirty" in r.stderr.lower()
        assert "[done]" not in (tmp_path / "data" / "plan.md").read_text()

    def test_story_tier_runs_after_verify(self, tmp_path):
        repo, env, g = make_repo(tmp_path)  # card Verify is green (true)
        (repo / ".xp" / "config.yml").write_text(CONFIG.replace("story: true", "story: false"))
        g("add", "-A")
        g("commit", "-qm", "red story tier")
        close(repo, env, "review")
        r = close(repo, env, "land")
        assert r.returncode != 0 and "tier" in (r.stderr + r.stdout).lower()
        assert "[done]" not in (tmp_path / "data" / "plan.md").read_text()

    def test_land_without_review_refused_cleanly(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        r = close(repo, env, "land")
        assert r.returncode == 2 and "review" in r.stderr
        assert "Traceback" not in r.stderr

    def test_unknown_story_refused_cleanly(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        r = subprocess.run(
            [sys.executable, str(CLOSE), "story", "story-999", "review", "--merge-mode", "local"],
            cwd=repo,
            env=env,
            capture_output=True,
            text=True,
        )
        assert r.returncode == 2 and "story-999" in r.stderr
        assert "Traceback" not in r.stderr


class TestSecondReviewRound:
    """Findings from /code-review on the story-002 diff."""

    def test_the_flip_preserves_a_sibling_lane_edit_made_DURING_land(self, tmp_path):
        """Was "post-merge flip preserves MAIN-SIDE changes": the flip was written
        after the merge so trunk's plan edits survived it. Nothing merges the plan
        now — it is one file shared by every lane — so the surviving claim is that
        an edit landing DURING land is still there after it.

        The window is what makes this a check. cmd_land snapshots the plan to read
        the card, then runs Verify and the tier for minutes, then flips; an edit
        made before land ever starts is already IN that snapshot, so writing the
        snapshot back would keep it and the test would certify. The sibling write
        therefore rides the card's own Verify command, which is the one hook that
        fires inside the window. Fault-injected: `edit_plan(lambda _t:
        _flip_status(plan, story_id))` — the snapshot written back over merged
        truth — reds this and nothing else in the suite.

        printf SUBSTITUTES the story id rather than spelling it: the Verify line
        is itself a line of the plan, so an assertion on a string the command
        contains verbatim passes whether or not the append ever ran."""
        sibling = "#### %s — sibling lane   [done]\\nVerify: true\\n"
        repo, env, _g = make_repo(
            tmp_path, verify=f"printf '{sibling}' story-043 >> \"$XP_DATA/plan.md\""
        )
        close(repo, env, "review")
        r = close(repo, env, "land")
        assert r.returncode == 0, r.stderr
        merged = (tmp_path / "data" / "plan.md").read_text()
        assert "#### story-043 — sibling lane   [done]" in merged  # the sibling edit survives
        assert "#### story-042 — demo story   [done]" in merged

    def test_main_motion_after_start_refused(self, tmp_path):
        repo, env, g = make_repo(tmp_path)
        close(repo, env, "review")
        g("checkout", "-q", "main")
        (repo / "unrelated.txt").write_text("x\n")
        g("add", "-A")
        g("commit", "-qm", "main moved")
        g("checkout", "-q", "story-042-branch")
        r = close(repo, env, "land")
        assert r.returncode == 2 and "main" in (r.stderr + r.stdout)
        assert "[done]" not in (tmp_path / "data" / "plan.md").read_text()

    def test_local_dry_run_performs_no_mutation(self, tmp_path):
        repo, env, g = make_repo(tmp_path)
        close(repo, env, "review")
        r = close(repo, env, "land", "--dry-run")
        assert r.returncode == 0
        assert "[done]" not in (tmp_path / "data" / "plan.md").read_text()
        assert g("log", "main", "--oneline").stdout.count("\n") == 1  # no merge happened
        r2 = close(repo, env, "land")
        assert r2.returncode == 0, "marker must survive a dry-run"

    def test_close_on_default_branch_refused(self, tmp_path):
        repo, env, g = make_repo(tmp_path)
        g("checkout", "-q", "main")
        g("merge", "-q", "--ff-only", "story-042-branch")
        r = close(repo, env, "review")
        assert r.returncode == 2 and "main" in r.stderr

    def test_missing_verify_line_refused(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        plan = tmp_path / "data" / "plan.md"
        plan.write_text(plan.read_text().replace("Verify: true\n", ""))
        close(repo, env, "review")
        r = close(repo, env, "land")
        assert r.returncode == 2 and "verify" in r.stderr.lower()

    def test_master_default_branch_supported(self, tmp_path):
        repo, env, g = make_repo(tmp_path, branch="master")
        close(repo, env, "review")
        r = close(repo, env, "land")
        assert r.returncode == 0, r.stderr
        assert "Review round 1" in g("log", "master", "-1", "--format=%B").stdout

    def test_pr_mode_detects_origin_trunk_motion(self, tmp_path):
        repo, env, g = make_repo(tmp_path)
        origin = tmp_path / "origin.git"
        subprocess.run(["git", "init", "-q", "--bare", str(origin)], env=env, check=True)
        g("remote", "add", "origin", str(origin))
        g("push", "-q", "origin", "main", "story-042-branch")
        close(repo, env, "review")
        # origin/main moves while local main stays put (the pr-mode workflow shape)
        g("checkout", "-q", "main")
        (repo / "unrelated.txt").write_text("x\n")
        g("add", "-A")
        g("commit", "-qm", "landed on origin")
        old = g("rev-parse", "HEAD~1").stdout.strip()
        g("push", "-q", "origin", "main")
        g("reset", "-q", "--hard", "HEAD~1")
        # stale tracking ref: only a real fetch can observe the motion
        g("update-ref", "refs/remotes/origin/main", old)
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
                "--dry-run",
            ],
            cwd=repo,
            env=env,
            capture_output=True,
            text=True,
        )
        assert r.returncode == 2 and "moved" in r.stderr

    def test_local_trunk_motion_with_remote_present_refused(self, tmp_path):
        repo, env, g = make_repo(tmp_path)
        origin = tmp_path / "origin.git"
        subprocess.run(["git", "init", "-q", "--bare", str(origin)], env=env, check=True)
        g("remote", "add", "origin", str(origin))
        g("push", "-q", "origin", "main", "story-042-branch")
        close(repo, env, "review")
        # commit lands on LOCAL main only; origin/main stays put (local-mode workflow)
        g("checkout", "-q", "main")
        (repo / "unrelated.txt").write_text("x\n")
        g("add", "-A")
        g("commit", "-qm", "local main moved")
        g("checkout", "-q", "story-042-branch")
        r = close(repo, env, "land")
        assert r.returncode == 2 and "moved" in r.stderr
        assert "[done]" not in (tmp_path / "data" / "plan.md").read_text()
