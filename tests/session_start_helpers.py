"""Shared fixtures for the SessionStart hook suites, split at story-027 when
test_session_start.py hit constraint 8's 500-line cap."""

import json
import subprocess
import sys
from pathlib import Path

HOOK = Path(__file__).parent.parent / "plugins" / "xp-plugin" / "scripts" / "session_start.py"
HOOKS_JSON = Path(__file__).parent.parent / "plugins" / "xp-plugin" / "hooks" / "hooks.json"


def run_hook(cwd, data_dir, session_id="sess-abc123"):
    stdin = json.dumps({"cwd": str(cwd), "session_id": session_id, "source": "startup"})
    return subprocess.run(
        [sys.executable, str(HOOK)],
        input=stdin,
        env={"PATH": "/usr/bin:/bin", "HOME": str(data_dir), "XP_DATA": str(data_dir / "xp")},
        cwd=cwd,
        capture_output=True,
        text=True,
    )


def xp_repo(tmp_path):
    repo = tmp_path / "repo"
    (repo / ".xp").mkdir(parents=True)
    env = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path)}
    g = lambda *a: subprocess.run(  # noqa: E731
        ["git", *a], cwd=repo, env=env, capture_output=True, text=True
    )
    g("init", "-q", "-b", "main")
    g("config", "user.email", "t@t")
    g("config", "user.name", "t")
    (tmp_path / "xp").mkdir(parents=True, exist_ok=True)
    (tmp_path / "xp" / "plan.md").write_text(
        "# plan\n#### story-042 — demo   [in-progress]\nVerify: true\n"
    )
    (repo / ".xp" / "constraints.md").write_text("# Constraints\nCONSTRAINT-SENTINEL\n")
    (repo / "f.py").write_text("A = 1\n")
    g("add", "-A")
    g("commit", "-qm", "base")
    return repo, g


def run_hook_as(cwd, data_dir, role=None):
    """Same hook, with XP_ROLE set — spawn exports it for teammate sessions."""
    env = {"PATH": "/usr/bin:/bin", "HOME": str(data_dir), "XP_DATA": str(data_dir / "xp")}
    if role is not None:
        env["XP_ROLE"] = role
    return subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps({"cwd": str(cwd), "session_id": "sess-role", "source": "startup"}),
        env=env,
        cwd=cwd,
        capture_output=True,
        text=True,
    )
