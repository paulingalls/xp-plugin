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
