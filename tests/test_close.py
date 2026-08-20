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


def make_repo(tmp_path, status="in-progress", verify="true"):
    repo = tmp_path / "repo"
    (repo / ".xp").mkdir(parents=True)
    env = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path), "XP_DATA": str(tmp_path / "data")}
    g = lambda *a, **k: subprocess.run(  # noqa: E731
        ["git", *a], cwd=repo, env=env, capture_output=True, text=True, **k
    )
    g("init", "-q", "-b", "main")
    g("config", "user.email", "t@t")
    g("config", "user.name", "t")
    (repo / ".xp" / "plan.md").write_text(CARD.format(status=status, verify=verify))
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
        assert "gh pr merge" in r.stdout
