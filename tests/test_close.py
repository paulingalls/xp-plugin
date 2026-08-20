"""story-002: close.py story-close pipeline. Verify: pytest -q tests/test_close.py"""

import json
import subprocess
import sys
from pathlib import Path

CLOSE = Path(__file__).parent.parent / "plugins" / "xp-plugin" / "scripts" / "close.py"
WORK = Path(__file__).parent.parent / "plugins" / "xp-plugin" / "scripts" / "work.py"

CARD = """# plan
## Milestone 1
### Sprint 1
#### story-042 — demo story   [{status}]
Context: demo.
Files: src/thing.py
AC:
- Given X, When Y, Then Z
Verify: {verify}
"""


CONFIG = "roles:\n  reviewer: claude/opus\ntests:\n  story: true\n"


def stub_reviewer(tmp_path, result="VERDICT: clean", exit_code=0, raw=None):
    """A fake `claude` that APPENDS one JSONL record per launch.

    Append, not overwrite: an overwriting stub makes "the reviewer was not
    launched again" pass vacuously by re-reading the previous launch's record.
    """
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    rec = tmp_path / "launches.jsonl"
    payload = raw if raw is not None else json.dumps({"result": result})
    (bin_dir / "claude").write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, sys\n"
        f"open({str(rec)!r}, 'a').write(json.dumps({{'argv': sys.argv[1:],"
        f" 'env': dict(os.environ), 'stdin': sys.stdin.read()}}) + '\\n')\n"
        f"sys.stdout.write({payload!r})\n"
        f"sys.exit({exit_code})\n"
    )
    (bin_dir / "claude").chmod(0o755)
    return bin_dir


def launches(tmp_path):
    rec = tmp_path / "launches.jsonl"
    return [json.loads(ln) for ln in rec.read_text().splitlines()] if rec.exists() else []


def marker(tmp_path, story_id="story-042"):
    return json.loads((tmp_path / "data" / "markers" / f"{story_id}.close.json").read_text())


def make_repo(tmp_path, status="in-progress", verify="true", branch="main"):
    repo = tmp_path / "repo"
    (repo / ".xp").mkdir(parents=True)
    env = {
        "PATH": f"{stub_reviewer(tmp_path)}:/usr/bin:/bin",
        "HOME": str(tmp_path),
        "XP_DATA": str(tmp_path / "data"),
    }
    g = lambda *a, **k: subprocess.run(  # noqa: E731
        ["git", *a], cwd=repo, env=env, capture_output=True, text=True, **k
    )
    g("init", "-q", "-b", branch)
    g("config", "user.email", "t@t")
    g("config", "user.name", "t")
    (repo / ".xp" / "plan.md").write_text(CARD.format(status=status, verify=verify))
    (repo / ".xp" / "config.yml").write_text(CONFIG)
    (repo / ".xp" / "constraints.md").write_text("# Constraints\n1. CONSTRAINT-SENTINEL\n")
    (repo / ".xp" / "system.md").write_text("# System\nSYSTEM-SENTINEL\n")
    (repo / "VALUES.md").write_text("# XP Values\nVALUES-SENTINEL\n")
    (repo / "src").mkdir()
    (repo / "src" / "thing.py").write_text("A = 1\n")
    g("add", "-A")
    g("commit", "-qm", "base")
    g("checkout", "-qb", "story-042-branch")
    (repo / "src" / "thing.py").write_text("A = 2\n")
    g("add", "-A")
    g("commit", "-qm", "story work")
    return repo, env, g


def close(repo, env, *args):
    return subprocess.run(
        [sys.executable, str(CLOSE), "story", "story-042", *args, "--merge-mode", "local"],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
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
        assert "VERDICT: clean" in body
        assert "[done]" in (repo / ".xp" / "plan.md").read_text()

    def test_drift_resets_to_reviewing_with_delta(self, tmp_path):
        repo, env, g = make_repo(tmp_path)
        close(repo, env, "review")
        (repo / "src" / "thing.py").write_text("A = 4\n")
        g("add", "-A")
        g("commit", "-qm", "fix from review")
        r = close(repo, env, "land")
        assert r.returncode == 2  # not merged
        assert "A = 4" in launches(tmp_path)[1]["stdin"]  # delta went to the reviewer
        assert "[done]" not in (repo / ".xp" / "plan.md").read_text()

    def test_conflicting_main_aborts_back_to_reviewing(self, tmp_path):
        repo, env, g = make_repo(tmp_path)
        close(repo, env, "review")
        g("checkout", "-q", "main")
        (repo / "src" / "thing.py").write_text("A = 9\n")
        g("add", "-A")
        g("commit", "-qm", "conflicting")
        g("checkout", "-q", "story-042-branch")
        close(repo, env, "review")  # re-baseline: trunk-motion guard fires otherwise
        r = close(repo, env, "land")
        assert r.returncode != 0 and "conflict" in (r.stderr + r.stdout).lower()
        assert "[done]" not in (repo / ".xp" / "plan.md").read_text()
        assert g("status", "--porcelain").stdout == ""  # no half-merged tree left behind

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
        assert "gh pr create" in r.stdout and "VERDICT: clean" in r.stdout
        merge_lines = [ln for ln in r.stdout.splitlines() if "gh pr merge" in ln]
        assert len(merge_lines) == 1
        assert "--merge" in merge_lines[0] and "--delete-branch" in merge_lines[0]
        assert "VERDICT: clean" in merge_lines[0]  # verdict rides the merge, not only create
        assert any(ln.startswith("git push") for ln in r.stdout.splitlines())

    def test_reviewed_dirty_tree_refused(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        close(repo, env, "review")
        (repo / "fixed.txt").write_text("untracked dirt\n")
        r = close(repo, env, "land")
        assert r.returncode == 2 and "dirty" in r.stderr.lower()
        assert "[done]" not in (repo / ".xp" / "plan.md").read_text()

    def test_story_tier_runs_after_verify(self, tmp_path):
        repo, env, g = make_repo(tmp_path)  # card Verify is green (true)
        (repo / ".xp" / "config.yml").write_text(CONFIG.replace("story: true", "story: false"))
        g("add", "-A")
        g("commit", "-qm", "red story tier")
        close(repo, env, "review")
        r = close(repo, env, "land")
        assert r.returncode != 0 and "tier" in (r.stderr + r.stdout).lower()
        assert "[done]" not in (repo / ".xp" / "plan.md").read_text()

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

    def test_post_merge_plan_flip_preserves_main_side_changes(self, tmp_path):
        repo, env, g = make_repo(tmp_path)
        close(repo, env, "review")
        g("checkout", "-q", "main")
        plan = repo / ".xp" / "plan.md"
        plan.write_text(plan.read_text() + "#### story-043 — other   [done]\nVerify: true\n")
        g("add", "-A")
        g("commit", "-qm", "story-043 done on main")
        g("checkout", "-q", "story-042-branch")
        close(repo, env, "review")  # re-baseline after main moved
        r = close(repo, env, "land")
        assert r.returncode == 0, r.stderr
        merged = g("show", "main:.xp/plan.md").stdout
        assert "#### story-043 — other   [done]" in merged  # main-side change survives
        assert "#### story-042 — demo story   [done]" in merged

    def test_every_drift_costs_a_review(self, tmp_path):
        repo, env, g = make_repo(tmp_path)
        close(repo, env, "review")
        (repo / "src" / "thing.py").write_text("A = 4\n")
        g("add", "-A")
        g("commit", "-qm", "post-review fix")
        assert close(repo, env, "land").returncode == 2
        # a SECOND drift must cost a SECOND review — re-baselining is earned by
        # the delta review, never by re-running land
        (repo / "src" / "thing.py").write_text("A = 5\n")
        g("add", "-A")
        g("commit", "-qm", "another post-review fix")
        assert close(repo, env, "land").returncode == 2
        assert len(launches(tmp_path)) == 3, "full review + one delta review per drift"
        assert "A = 5" in launches(tmp_path)[2]["stdin"]
        assert "[done]" not in (repo / ".xp" / "plan.md").read_text()

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
        assert "[done]" not in (repo / ".xp" / "plan.md").read_text()

    def test_local_dry_run_performs_no_mutation(self, tmp_path):
        repo, env, g = make_repo(tmp_path)
        close(repo, env, "review")
        r = close(repo, env, "land", "--dry-run")
        assert r.returncode == 0
        assert "[done]" not in (repo / ".xp" / "plan.md").read_text()
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
        repo, env, g = make_repo(tmp_path)
        plan = repo / ".xp" / "plan.md"
        plan.write_text(plan.read_text().replace("Verify: true\n", ""))
        g("add", "-A")
        g("commit", "-qm", "drop verify line")
        close(repo, env, "review")
        r = close(repo, env, "land")
        assert r.returncode == 2 and "verify" in r.stderr.lower()

    def test_master_default_branch_supported(self, tmp_path):
        repo, env, g = make_repo(tmp_path, branch="master")
        close(repo, env, "review")
        r = close(repo, env, "land")
        assert r.returncode == 0, r.stderr
        assert "VERDICT: clean" in g("log", "master", "-1", "--format=%B").stdout

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
        assert "[done]" not in (repo / ".xp" / "plan.md").read_text()


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
        assert "VERDICT: clean" in g("log", "sprint-001", "-1", "--format=%B").stdout
        assert "[done]" in g("show", "sprint-001:.xp/plan.md").stdout
        assert "VERDICT" not in g("log", "main", "--format=%B").stdout  # main untouched

    def test_sprint_release_without_branch_key_falls_back_to_default(self, tmp_path):
        repo, env, g = make_repo(tmp_path)
        (repo / ".xp" / "config.yml").write_text("release: sprint\n" + CONFIG)
        g("add", "-A")
        g("commit", "-qm", "sprint release, no branch yet")
        close(repo, env, "review")
        r = close(repo, env, "land")
        assert r.returncode == 0, r.stderr
        assert "VERDICT: clean" in g("log", "main", "-1", "--format=%B").stdout

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
        assert "VERDICT: clean" in g("log", "main", "-1", "--format=%B").stdout

    def test_guards_watch_sprint_branch_not_main(self, tmp_path):
        repo, env, g = self.sprint_repo(tmp_path)
        close(repo, env, "review")
        g("checkout", "-q", "sprint-001")
        (repo / "sprint-file.txt").write_text("x\n")
        g("add", "-A")
        g("commit", "-qm", "sprint branch moved")
        g("checkout", "-q", "story-042-branch")
        r = close(repo, env, "land")
        assert r.returncode == 2 and "moved" in r.stderr

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
        (repo / "sprint-file.txt").write_text("x\n")
        g("add", "-A")
        g("commit", "-qm", "sprint branch moved")
        g("checkout", "-q", "story-042-branch")
        r = close(repo, env, "land")
        assert r.returncode == 2 and "moved" in r.stderr

    def test_pr_refusal_precedes_moved_check(self, tmp_path):
        repo, env, g = self.sprint_repo(tmp_path)
        origin = tmp_path / "origin.git"
        subprocess.run(["git", "init", "-q", "--bare", str(origin)], env=env, check=True)
        g("remote", "add", "origin", str(origin))
        g("push", "-q", "origin", "sprint-001")
        close(repo, env, "review")
        g("checkout", "-q", "sprint-001")
        (repo / "sprint-file.txt").write_text("x\n")
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
        assert r.returncode == 2 and "local" in r.stderr and "moved" not in r.stderr


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
        repo, env, g = make_repo(tmp_path)
        (repo / ".xp" / "plan.md").unlink()
        g("add", "-A")
        g("commit", "-qm", "no plan")
        r = close(repo, env, "review")
        assert r.returncode == 2 and "plan.md" in r.stderr and "Traceback" not in r.stderr

    def test_bracketless_story_header_refused_cleanly(self, tmp_path):
        repo, env, g = make_repo(tmp_path)
        plan = repo / ".xp" / "plan.md"
        plan.write_text(plan.read_text().replace("   [in-progress]", ""))
        g("add", "-A")
        g("commit", "-qm", "malformed header")
        r = close(repo, env, "review")
        assert r.returncode == 2 and "Traceback" not in r.stderr


class TestPipelineReceivedVerdict:
    """story-008 AC 1/4: the pipeline spawns the reviewer and records its verdict."""

    def test_review_launches_the_reviewer_with_the_bundle_inlined(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        r = close(repo, env, "review")
        assert r.returncode == 0, r.stderr
        (launch,) = launches(tmp_path)
        argv = launch["argv"]
        assert "--plugin-dir" in argv and "-p" in argv
        assert argv[argv.index("--model") + 1] == "opus"
        assert argv[argv.index("--output-format") + 1] == "json"
        prompt = launch["stdin"]
        assert "fault-inject" in prompt.lower()  # the charter, inlined
        assert "demo story" in prompt  # the card
        assert "-A = 1" in prompt and "+A = 2" in prompt  # the cumulative diff
        assert "CONSTRAINT-SENTINEL" in prompt and "SYSTEM-SENTINEL" in prompt

    def test_the_spawned_reviewer_is_not_a_lead_and_cannot_close(self, tmp_path):
        """N10: the only thing pinning the reviewer's role otherwise lives in
        test_spawn.py, which this story's Verify does not run."""
        repo, env, _g = make_repo(tmp_path)
        close(repo, env, "review")
        (launch,) = launches(tmp_path)
        assert launch["env"]["XP_ROLE"] == "reviewer"

    def test_reviewer_cannot_edit_the_lead_tree_it_is_reviewing(self, tmp_path):
        """G1: spawn's bypass posture was justified by a THROWAWAY worktree; the
        reviewer runs in the lead's live tree, so the write tools are denied."""
        repo, env, _g = make_repo(tmp_path)
        close(repo, env, "review")
        (launch,) = launches(tmp_path)
        argv = launch["argv"]
        denied = argv[argv.index("--disallowedTools") + 1]
        assert {"Edit", "Write", "NotebookEdit"} <= set(denied.split(","))

    def test_verdict_lands_in_the_marker_verbatim(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        stub_reviewer(tmp_path, result="findings...\nVERDICT: 3 findings (1 gating)\ntail")
        close(repo, env, "review")
        assert marker(tmp_path)["verdicts"] == ["VERDICT: 3 findings (1 gating)"]

    def test_reviewed_sha_is_captured_before_the_launch(self, tmp_path):
        """G1: read after the launch, a reviewer that commits certifies itself."""
        repo, env, g = make_repo(tmp_path)
        head_before = g("rev-parse", "HEAD").stdout.strip()
        close(repo, env, "review")
        assert marker(tmp_path)["reviewed_sha"] == head_before

    def test_a_reviewer_that_commits_is_refused_not_certified(self, tmp_path):
        """G1 fault-injection: the stub commits, exactly as a bypassed agent could."""
        repo, env, _g = make_repo(tmp_path)
        bin_dir = tmp_path / "bin"
        (bin_dir / "claude").write_text(
            "#!/bin/sh\n"
            "echo 'x = 1' >> src/thing.py\n"
            "git add -A && git commit -qm 'reviewer wrote this'\n"
            'printf \'{"result": "VERDICT: clean"}\'\n'
        )
        (bin_dir / "claude").chmod(0o755)
        r = close(repo, env, "review")
        assert r.returncode == 2 and "reviewer" in r.stderr.lower()
        assert not (tmp_path / "data" / "markers" / "story-042.close.json").exists()

    def test_no_verdict_line_means_no_merge(self, tmp_path):
        """AC 4."""
        repo, env, _g = make_repo(tmp_path)
        stub_reviewer(tmp_path, result="I read the diff and it seemed fine.")
        close(repo, env, "review")
        r = close(repo, env, "land")
        assert r.returncode == 2 and "verdict" in r.stderr.lower()
        assert "[done]" not in (repo / ".xp" / "plan.md").read_text()

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


class TestDriftReReview:
    """story-008 AC 2: drift is reviewed in-pipeline, on the delta only."""

    def test_drift_reviews_the_delta_and_still_refuses_to_land(self, tmp_path):
        repo, env, g = make_repo(tmp_path)
        close(repo, env, "review")
        (repo / "src" / "thing.py").write_text("A = 3\n")
        g("add", "-A")
        g("commit", "-qm", "post-review fix")
        r = close(repo, env, "land")
        assert r.returncode == 2
        assert "[done]" not in (repo / ".xp" / "plan.md").read_text()
        assert len(launches(tmp_path)) == 2, "the delta review must run in-pipeline"
        delta_prompt = launches(tmp_path)[1]["stdin"]
        assert "+A = 3" in delta_prompt
        assert "-A = 1" not in delta_prompt, "the delta is reviewed, not the whole story again"

    def test_delta_rebaseline_keeps_both_verdicts_and_lands(self, tmp_path):
        """N1: a delta 'clean' must not erase round 1's findings from the record."""
        repo, env, g = make_repo(tmp_path)
        stub_reviewer(tmp_path, result="VERDICT: 2 findings (1 gating)")
        close(repo, env, "review")
        (repo / "src" / "thing.py").write_text("A = 3\n")
        g("add", "-A")
        g("commit", "-qm", "fix the gating finding")
        stub_reviewer(tmp_path, result="VERDICT: clean")
        close(repo, env, "land")
        assert marker(tmp_path)["verdicts"] == [
            "VERDICT: 2 findings (1 gating)",
            "VERDICT: clean",
        ]
        r = close(repo, env, "land")
        assert r.returncode == 0, r.stderr
        body = g("log", "-1", "--format=%B", "main").stdout
        assert "VERDICT: 2 findings (1 gating)" in body and "VERDICT: clean" in body

    def test_delta_rebaseline_does_not_clear_the_trunk_guard(self, tmp_path):
        """G4: trunk motion during the review window must survive the re-baseline."""
        repo, env, g = make_repo(tmp_path)
        close(repo, env, "review")
        g("checkout", "-q", "main")
        (repo / "other.txt").write_text("someone else landed a story\n")
        g("add", "-A")
        g("commit", "-qm", "trunk moved")
        g("checkout", "-q", "story-042-branch")
        (repo / "src" / "thing.py").write_text("A = 3\n")
        g("add", "-A")
        g("commit", "-qm", "post-review fix")
        assert close(repo, env, "land").returncode == 2  # drift; delta reviewed
        r = close(repo, env, "land")
        assert r.returncode == 2 and "moved" in r.stderr


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
        assert rec["verdicts"] == ["VERDICT: clean"]
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

    def test_an_enormous_verdict_cannot_evict_constraints_from_the_next_session(self, tmp_path):
        """G5: session_start truncates its TAIL, and constraints.md is last."""
        repo, env, _g = make_repo(tmp_path)
        stub_reviewer(tmp_path, result="VERDICT: " + "x" * 4000)
        close(repo, env, "review")
        assert len(marker(tmp_path)["verdicts"][0]) <= 200


class TestStoryReviewFindings:
    """story-008 close review, run by this story's own pipeline."""

    def test_a_delta_without_a_verdict_cannot_ride_round_ones(self, tmp_path):
        """G1: reviewed_sha advanced on a verdict-less delta review, so round 1's
        verdict satisfied land's check and unreviewed work merged under it."""
        repo, env, g = make_repo(tmp_path)
        close(repo, env, "review")  # records VERDICT: clean
        (repo / "src" / "thing.py").write_text("A = 666\n")
        g("add", "-A")
        g("commit", "-qm", "work added after the review")
        stub_reviewer(tmp_path, result="I ran out of turns before writing a verdict.")
        assert close(repo, env, "land").returncode == 2  # drift: delta reviewed
        r = close(repo, env, "land")
        assert r.returncode == 2, "merged under a verdict that never saw the delta"
        assert "A = 666" not in g("show", "main:src/thing.py").stdout

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
        assert "[done]" not in (repo / ".xp" / "plan.md").read_text()

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
        repo, env, g = make_repo(tmp_path)
        plan = repo / ".xp" / "plan.md"
        plan.write_text(plan.read_text().replace("#### story-042 — demo story", "#### story-042"))
        g("add", "-A")
        g("commit", "-qm", "dashless header")
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
        assert "[done]" in g("show", "origin/main:.xp/plan.md").stdout, "trunk never learned"
