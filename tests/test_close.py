"""story-002: close.py story-close pipeline. Verify: pytest -q tests/test_close.py"""

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


def make_repo(tmp_path, status="in-progress", verify="true", branch="main"):
    repo = tmp_path / "repo"
    (repo / ".xp").mkdir(parents=True)
    env = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path), "XP_DATA": str(tmp_path / "data")}
    g = lambda *a, **k: subprocess.run(  # noqa: E731
        ["git", *a], cwd=repo, env=env, capture_output=True, text=True, **k
    )
    g("init", "-q", "-b", branch)
    g("config", "user.email", "t@t")
    g("config", "user.name", "t")
    (repo / ".xp" / "plan.md").write_text(CARD.format(status=status, verify=verify))
    (repo / ".xp" / "config.yml").write_text("tests:\n  story: true\n")
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
        r = close(repo, env, "start")
        assert r.returncode == 2 and "dirty" in r.stderr.lower()

    def test_ready_story_refused(self, tmp_path):
        repo, env, _g = make_repo(tmp_path, status="ready")
        r = close(repo, env, "start")
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
        r = close(repo, env, "start")
        assert r.returncode == 0, r.stderr
        for sentinel in (
            "VALUES-SENTINEL",
            "CONSTRAINT-SENTINEL",
            "SYSTEM-SENTINEL",
            "A = 2",
            "demo story",
            "filed-during-story",
        ):
            assert sentinel in r.stdout, f"bundle missing {sentinel}"


class TestReviewed:
    def test_without_verdict_refused(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        close(repo, env, "start")
        r = close(repo, env, "reviewed", "--verdict", "")
        assert r.returncode == 2 and "verdict" in r.stderr.lower()

    def test_red_verify_aborts_before_merge_naming_command(self, tmp_path):
        repo, env, g = make_repo(tmp_path, verify="false")
        close(repo, env, "start")
        r = close(repo, env, "reviewed", "--verdict", "VERDICT: clean")
        assert r.returncode != 0 and "false" in (r.stderr + r.stdout)
        assert g("log", "main", "--oneline").stdout.count("\n") == 1  # no merge

    def test_green_close_merges_with_verdict_and_flips_status(self, tmp_path):
        repo, env, g = make_repo(tmp_path)
        close(repo, env, "start")
        r = close(repo, env, "reviewed", "--verdict", "VERDICT: clean")
        assert r.returncode == 0, r.stderr
        body = g("log", "main", "-1", "--format=%B").stdout
        assert "VERDICT: clean" in body
        assert "[done]" in (repo / ".xp" / "plan.md").read_text()

    def test_drift_resets_to_reviewing_with_delta(self, tmp_path):
        repo, env, g = make_repo(tmp_path)
        close(repo, env, "start")
        (repo / "src" / "thing.py").write_text("A = 4\n")
        g("add", "-A")
        g("commit", "-qm", "fix from review")
        r = close(repo, env, "reviewed", "--verdict", "VERDICT: clean")
        assert r.returncode == 2 and "A = 4" in r.stdout  # delta emitted, not merged
        assert "[done]" not in (repo / ".xp" / "plan.md").read_text()

    def test_conflicting_main_aborts_back_to_reviewing(self, tmp_path):
        repo, env, g = make_repo(tmp_path)
        close(repo, env, "start")
        g("checkout", "-q", "main")
        (repo / "src" / "thing.py").write_text("A = 9\n")
        g("add", "-A")
        g("commit", "-qm", "conflicting")
        g("checkout", "-q", "story-042-branch")
        close(repo, env, "start")  # re-baseline: trunk-motion guard fires otherwise
        r = close(repo, env, "reviewed", "--verdict", "VERDICT: clean")
        assert r.returncode != 0 and "conflict" in (r.stderr + r.stdout).lower()
        assert "[done]" not in (repo / ".xp" / "plan.md").read_text()
        assert g("status", "--porcelain").stdout == ""  # no half-merged tree left behind

    def test_pr_mode_dry_run_pins_gh_args(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        close(repo, env, "start")
        r = subprocess.run(
            [
                sys.executable,
                str(CLOSE),
                "story",
                "story-042",
                "reviewed",
                "--verdict",
                "VERDICT: clean",
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
        close(repo, env, "start")
        (repo / "fixed.txt").write_text("untracked dirt\n")
        r = close(repo, env, "reviewed", "--verdict", "VERDICT: clean")
        assert r.returncode == 2 and "dirty" in r.stderr.lower()
        assert "[done]" not in (repo / ".xp" / "plan.md").read_text()

    def test_story_tier_runs_after_verify(self, tmp_path):
        repo, env, g = make_repo(tmp_path)  # card Verify is green (true)
        (repo / ".xp" / "config.yml").write_text("tests:\n  story: false\n")
        g("add", "-A")
        g("commit", "-qm", "red story tier")
        close(repo, env, "start")
        r = close(repo, env, "reviewed", "--verdict", "VERDICT: clean")
        assert r.returncode != 0 and "tier" in (r.stderr + r.stdout).lower()
        assert "[done]" not in (repo / ".xp" / "plan.md").read_text()

    def test_reviewed_without_start_refused_cleanly(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        r = close(repo, env, "reviewed", "--verdict", "VERDICT: clean")
        assert r.returncode == 2 and "start" in r.stderr
        assert "Traceback" not in r.stderr

    def test_unknown_story_refused_cleanly(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        r = subprocess.run(
            [sys.executable, str(CLOSE), "story", "story-999", "start", "--merge-mode", "local"],
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
        close(repo, env, "start")
        g("checkout", "-q", "main")
        plan = repo / ".xp" / "plan.md"
        plan.write_text(plan.read_text() + "#### story-043 — other   [done]\nVerify: true\n")
        g("add", "-A")
        g("commit", "-qm", "story-043 done on main")
        g("checkout", "-q", "story-042-branch")
        close(repo, env, "start")  # re-baseline after main moved
        r = close(repo, env, "reviewed", "--verdict", "VERDICT: clean")
        assert r.returncode == 0, r.stderr
        merged = g("show", "main:.xp/plan.md").stdout
        assert "#### story-043 — other   [done]" in merged  # main-side change survives
        assert "#### story-042 — demo story   [done]" in merged

    def test_drift_does_not_self_clear(self, tmp_path):
        repo, env, g = make_repo(tmp_path)
        close(repo, env, "start")
        (repo / "src" / "thing.py").write_text("A = 4\n")
        g("add", "-A")
        g("commit", "-qm", "post-review fix")
        r1 = close(repo, env, "reviewed", "--verdict", "VERDICT: clean")
        assert r1.returncode == 2
        r2 = close(repo, env, "reviewed", "--verdict", "VERDICT: clean")
        assert r2.returncode == 2, "second identical invocation must not merge"
        assert "[done]" not in (repo / ".xp" / "plan.md").read_text()

    def test_main_motion_after_start_refused(self, tmp_path):
        repo, env, g = make_repo(tmp_path)
        close(repo, env, "start")
        g("checkout", "-q", "main")
        (repo / "unrelated.txt").write_text("x\n")
        g("add", "-A")
        g("commit", "-qm", "main moved")
        g("checkout", "-q", "story-042-branch")
        r = close(repo, env, "reviewed", "--verdict", "VERDICT: clean")
        assert r.returncode == 2 and "main" in (r.stderr + r.stdout)
        assert "[done]" not in (repo / ".xp" / "plan.md").read_text()

    def test_local_dry_run_performs_no_mutation(self, tmp_path):
        repo, env, g = make_repo(tmp_path)
        close(repo, env, "start")
        r = close(repo, env, "reviewed", "--verdict", "VERDICT: clean", "--dry-run")
        assert r.returncode == 0
        assert "[done]" not in (repo / ".xp" / "plan.md").read_text()
        assert g("log", "main", "--oneline").stdout.count("\n") == 1  # no merge happened
        r2 = close(repo, env, "reviewed", "--verdict", "VERDICT: clean")
        assert r2.returncode == 0, "marker must survive a dry-run"

    def test_close_on_default_branch_refused(self, tmp_path):
        repo, env, g = make_repo(tmp_path)
        g("checkout", "-q", "main")
        g("merge", "-q", "--ff-only", "story-042-branch")
        r = close(repo, env, "start")
        assert r.returncode == 2 and "main" in r.stderr

    def test_missing_verify_line_refused(self, tmp_path):
        repo, env, g = make_repo(tmp_path)
        plan = repo / ".xp" / "plan.md"
        plan.write_text(plan.read_text().replace("Verify: true\n", ""))
        g("add", "-A")
        g("commit", "-qm", "drop verify line")
        close(repo, env, "start")
        r = close(repo, env, "reviewed", "--verdict", "VERDICT: clean")
        assert r.returncode == 2 and "verify" in r.stderr.lower()

    def test_master_default_branch_supported(self, tmp_path):
        repo, env, g = make_repo(tmp_path, branch="master")
        close(repo, env, "start")
        r = close(repo, env, "reviewed", "--verdict", "VERDICT: clean")
        assert r.returncode == 0, r.stderr
        assert "VERDICT: clean" in g("log", "master", "-1", "--format=%B").stdout

    def test_pr_mode_detects_origin_trunk_motion(self, tmp_path):
        repo, env, g = make_repo(tmp_path)
        origin = tmp_path / "origin.git"
        subprocess.run(["git", "init", "-q", "--bare", str(origin)], env=env, check=True)
        g("remote", "add", "origin", str(origin))
        g("push", "-q", "origin", "main", "story-042-branch")
        close(repo, env, "start")
        # origin/main moves while local main stays put (the pr-mode workflow shape)
        g("checkout", "-q", "main")
        (repo / "unrelated.txt").write_text("x\n")
        g("add", "-A")
        g("commit", "-qm", "landed on origin")
        g("push", "-q", "origin", "main")
        g("reset", "-q", "--hard", "HEAD~1")
        g("checkout", "-q", "story-042-branch")
        r = subprocess.run(
            [
                sys.executable,
                str(CLOSE),
                "story",
                "story-042",
                "reviewed",
                "--verdict",
                "VERDICT: clean",
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
