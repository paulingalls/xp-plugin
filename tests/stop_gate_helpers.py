import json
import subprocess
import sys
from pathlib import Path

SCRIPTS = Path(__file__).parent.parent / "plugins" / "xp-plugin" / "scripts"
HOOKS_JSON = Path(__file__).parent.parent / "plugins" / "xp-plugin" / "hooks" / "hooks.json"


def repo_with_story(tmp_path, verify="pytest -q tests/test_x.py"):
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
        f"# plan\n#### story-042 — demo   [in-progress]\nVerify: {verify}\n"
    )
    (repo / "f.py").write_text("A = 1\n")
    g("add", "-A")
    g("commit", "-qm", "base")
    return repo, g


def run_script(name, payload, repo, tmp_path):
    return subprocess.run(
        [sys.executable, str(SCRIPTS / name)],
        input=json.dumps(payload),
        env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path), "XP_DATA": str(tmp_path / "xp")},
        cwd=repo,
        capture_output=True,
        text=True,
    )


def success_payload(command, session="sess-1"):
    """Captured PostToolUse shape: NO exit_code — the event itself means success."""
    return {
        "session_id": session,
        "cwd": ".",
        "hook_event_name": "PostToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "tool_response": {"stdout": "ok", "stderr": "", "interrupted": False, "isImage": False},
    }


def failure_payload(command, code=1, session="sess-1", error=None):
    """Captured PostToolUseFailure shape: no tool_response, top-level error string."""
    return {
        "session_id": session,
        "cwd": ".",
        "hook_event_name": "PostToolUseFailure",
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "error": error if error is not None else f"Exit code {code}\nFAILED tests",
    }


def markers(tmp_path, session="sess-1"):
    d = tmp_path / "xp" / "markers"
    if not d.exists():
        return []
    return [json.loads(p.read_text()) for p in d.glob(f"{session}.*.test-status")]
