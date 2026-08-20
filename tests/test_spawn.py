"""story-007: spawn.py teammate launch. Verify: pytest -q tests/test_spawn.py"""

import json
import subprocess
import sys
from pathlib import Path

SPAWN = Path(__file__).parent.parent / "plugins" / "xp-plugin" / "scripts" / "spawn.py"

CARD = """# plan
## Milestone 1
### Sprint 1
#### story-042 — demo story   [{status}]
Context: demo.
Files: src/thing.py
AC:
- Given X, When Y, Then Z
Verify: true
Executor: {executor}
"""

CONFIG = """release: sprint
sprint_branch: {trunk}

roles:
  lead: claude/opus
  executor: claude/sonnet/medium
  reviewer: claude/opus

tests:
  story: true
"""


def make_repo(tmp_path, status="ready", executor="(default)", trunk="main"):
    """A repo whose HEAD is NOT the integration target, with a divergent commit:
    a spawn that omits the base argument branches off HEAD and the test reds."""
    repo = tmp_path / "repo"
    (repo / ".xp").mkdir(parents=True)
    env = {
        "PATH": f"{tmp_path / 'bin'}:/usr/bin:/bin",
        "HOME": str(tmp_path),
        "XP_DATA": str(tmp_path / "data"),
    }
    g = lambda *a: subprocess.run(  # noqa: E731
        ["git", *a], cwd=repo, env=env, capture_output=True, text=True
    )
    g("init", "-q", "-b", trunk)
    g("config", "user.email", "ada@example.com")
    g("config", "user.name", "Ada L")
    (repo / ".xp" / "plan.md").write_text(CARD.format(status=status, executor=executor))
    (repo / ".xp" / "config.yml").write_text(CONFIG.format(trunk=trunk))
    (repo / ".xp" / "constraints.md").write_text("# Constraints\n1. CONSTRAINT-SENTINEL\n")
    (repo / ".xp" / "system.md").write_text("# System\n- Worktree bootstrap: none needed\n")
    g("add", "-A")
    g("commit", "-qm", "base")
    g("checkout", "-qb", "elsewhere")
    (repo / "drift.txt").write_text("HEAD is not the trunk\n")
    g("add", "-A")
    g("commit", "-qm", "divergent")
    return repo, env, g


def stub_claude(tmp_path):
    """A fake `claude` that records argv, env and stdin — the launch contract is
    otherwise unpinned, and a teammate that cannot edit exits 0 with prose."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    rec = tmp_path / "launch.json"
    (bin_dir / "claude").write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, sys\n"
        f"json.dump({{'argv': sys.argv[1:], 'env': dict(os.environ),"
        f" 'stdin': sys.stdin.read()}}, open({str(rec)!r}, 'w'))\n"
    )
    (bin_dir / "claude").chmod(0o755)
    return rec


def spawn(repo, env, *args):
    return subprocess.run(
        [sys.executable, str(SPAWN), *args],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
    )


class TestLaunchContract:
    def test_argv_carries_model_effort_plugin_dir_and_permission_posture(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        rec = stub_claude(tmp_path)
        r = spawn(repo, env, "story-042")
        assert r.returncode == 0, r.stderr
        argv = json.loads(rec.read_text())["argv"]
        assert "-p" in argv
        assert argv[argv.index("--model") + 1] == "sonnet"
        assert argv[argv.index("--effort") + 1] == "medium"
        # without --plugin-dir the teammate loads no hooks, agents or skills:
        # a worktree session applies no project-scoped marketplace enablement
        assert Path(argv[argv.index("--plugin-dir") + 1]).name == "xp-plugin"
        # headless denies tool permission by default -> prose-only teammate, exit 0
        assert "--dangerously-skip-permissions" in argv
        assert argv[argv.index("--output-format") + 1] == "json"

    def test_prompt_arrives_on_stdin_not_argv(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        rec = stub_claude(tmp_path)
        assert spawn(repo, env, "story-042").returncode == 0
        launch = json.loads(rec.read_text())
        assert "CONSTRAINT-SENTINEL" in launch["stdin"]
        assert not any("CONSTRAINT-SENTINEL" in a for a in launch["argv"])

    def test_role_env_exported_so_teammate_does_not_get_the_lead_profile(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        rec = stub_claude(tmp_path)
        assert spawn(repo, env, "story-042").returncode == 0
        assert json.loads(rec.read_text())["env"].get("XP_ROLE") == "teammate"


def trunk_sha(repo, env, trunk="main"):
    return subprocess.run(
        ["git", "rev-parse", f"refs/heads/{trunk}"],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
    ).stdout.strip()


def in_tree(tree, env, *args):
    return subprocess.run(
        ["git", *args], cwd=tree, env=env, capture_output=True, text=True
    ).stdout.strip()


class TestWorktree:
    def test_worktree_branches_off_the_integration_target_not_head(self, tmp_path):
        """HEAD carries a divergent commit the trunk does not have, so a
        `worktree add` that omits the base argument reds here instead of
        passing because HEAD happened to be the trunk (constraints.md #2)."""
        repo, env, _g = make_repo(tmp_path)
        stub_claude(tmp_path)
        assert spawn(repo, env, "story-042").returncode == 0
        tree = tmp_path / "data" / "worktrees" / "story-042"
        assert tree.is_dir()
        assert not (tree / "drift.txt").exists()  # the divergent commit is absent
        assert trunk_sha(repo, env) in in_tree(tree, env, "log", "--format=%H")

    def test_branch_is_namespaced_per_identity_so_clones_cannot_collide(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        stub_claude(tmp_path)
        assert spawn(repo, env, "story-042").returncode == 0
        first = in_tree(
            tmp_path / "data" / "worktrees" / "story-042", env, "branch", "--show-current"
        )
        assert first == "ada/story-042-demo-story"

        other = tmp_path / "clone2"
        subprocess.run(["git", "clone", "-q", str(repo), str(other)], env=env, check=True)
        env2 = dict(env, XP_DATA=str(tmp_path / "data2"))
        for k, v in (("user.email", "grace@example.com"), ("user.name", "Grace H")):
            subprocess.run(["git", "config", k, v], cwd=other, env=env2, check=True)
        subprocess.run(["git", "checkout", "-q", "main"], cwd=other, env=env2)
        assert spawn(other, env2, "story-042").returncode == 0
        second = in_tree(
            tmp_path / "data2" / "worktrees" / "story-042", env2, "branch", "--show-current"
        )
        assert second == "grace/story-042-demo-story"
        assert first != second

    def test_status_flip_is_committed_in_the_worktree(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        stub_claude(tmp_path)
        assert spawn(repo, env, "story-042").returncode == 0
        tree = tmp_path / "data" / "worktrees" / "story-042"
        assert "[in-progress]" in (tree / ".xp" / "plan.md").read_text()
        assert in_tree(tree, env, "status", "--porcelain") == ""
        # the lead's tree still reads [ready]: git is the memory, and the
        # reviewer sees the flip in the cumulative diff
        assert "[ready]" in (repo / ".xp" / "plan.md").read_text()

    def test_dry_run_creates_nothing(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        stub_claude(tmp_path)
        r = spawn(repo, env, "story-042", "--dry-run")
        assert r.returncode == 0 and "--plugin-dir" in r.stdout
        assert not (tmp_path / "data" / "worktrees" / "story-042").exists()
        assert "story-042" not in in_tree(repo, env, "branch", "--list")


class TestRefusals:
    def test_existing_worktree_refused(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        stub_claude(tmp_path)
        assert spawn(repo, env, "story-042").returncode == 0
        r = spawn(repo, env, "story-042")
        assert r.returncode == 2 and "already" in r.stderr

    def test_existing_branch_refused_when_the_worktree_is_gone(self, tmp_path):
        repo, env, _g = make_repo(tmp_path)
        stub_claude(tmp_path)
        assert spawn(repo, env, "story-042").returncode == 0
        subprocess.run(
            [
                "git",
                "worktree",
                "remove",
                "--force",
                str(tmp_path / "data" / "worktrees" / "story-042"),
            ],
            cwd=repo,
            env=env,
            check=True,
        )
        r = spawn(repo, env, "story-042")
        assert r.returncode == 2 and "branch" in r.stderr

    def test_non_ready_story_refused(self, tmp_path):
        repo, env, _g = make_repo(tmp_path, status="done")
        r = spawn(repo, env, "story-042")
        assert r.returncode == 2 and "ready" in r.stderr

    def test_codex_harness_refused_naming_sprint_3(self, tmp_path):
        repo, env, _g = make_repo(tmp_path, executor="codex/gpt-5/high")
        r = spawn(repo, env, "story-042")
        assert r.returncode == 2 and "Sprint 3" in r.stderr


class TestExecutorResolution:
    def test_card_executor_beats_config(self, tmp_path):
        repo, env, _g = make_repo(tmp_path, executor="claude/opus/high")
        rec = stub_claude(tmp_path)
        assert spawn(repo, env, "story-042").returncode == 0
        argv = json.loads(rec.read_text())["argv"]
        assert argv[argv.index("--model") + 1] == "opus"
        assert argv[argv.index("--effort") + 1] == "high"

    def test_cli_override_beats_the_card(self, tmp_path):
        repo, env, _g = make_repo(tmp_path, executor="claude/opus/high")
        rec = stub_claude(tmp_path)
        assert spawn(repo, env, "story-042", "claude/haiku").returncode == 0
        argv = json.loads(rec.read_text())["argv"]
        assert argv[argv.index("--model") + 1] == "haiku"
        assert "--effort" not in argv  # two-part spec: reviewer role shape (story-008)
