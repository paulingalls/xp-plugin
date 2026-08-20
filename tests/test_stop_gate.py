"""story-004: Stop advisory gate + bash test-status leg.

Verify: pytest -q tests/test_stop_gate.py
"""

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
    (repo / ".xp" / "plan.md").write_text(
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


def bash_payload(command, exit_code, session="sess-1"):
    # exact production shape (xp-agents fixtures): tool_response dict with exit_code
    return {
        "session_id": session,
        "cwd": ".",
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "tool_response": {"stdout": "", "stderr": "", "exit_code": exit_code},
    }


def marker(tmp_path, session="sess-1"):
    p = tmp_path / "xp" / "markers" / f"{session}.test-status"
    return json.loads(p.read_text()) if p.exists() else None


class TestBashStatus:
    def test_verify_match_records_red_then_green_overwrites(self, tmp_path):
        repo, _g = repo_with_story(tmp_path)
        payload = bash_payload("cd x && pytest -q tests/test_x.py", 1)
        run_script("bash_status.py", payload, repo, tmp_path)
        assert marker(tmp_path)["red"] is True
        run_script("bash_status.py", bash_payload("pytest -q tests/test_x.py", 0), repo, tmp_path)
        assert marker(tmp_path)["red"] is False

    def test_non_verify_failure_writes_nothing(self, tmp_path):
        repo, _g = repo_with_story(tmp_path)
        run_script("bash_status.py", bash_payload("pytest -q tests/other.py", 1), repo, tmp_path)
        assert marker(tmp_path) is None

    def test_missing_exit_code_writes_nothing(self, tmp_path):
        repo, _g = repo_with_story(tmp_path)
        p = bash_payload("pytest -q tests/test_x.py", 1)
        del p["tool_response"]["exit_code"]
        run_script("bash_status.py", p, repo, tmp_path)
        assert marker(tmp_path) is None

    def test_matches_any_in_progress_story(self, tmp_path):
        repo, _g = repo_with_story(tmp_path)
        plan = repo / ".xp" / "plan.md"
        plan.write_text(
            plan.read_text() + "#### story-043 — other   [in-progress]\nVerify: bun test x\n"
        )
        run_script("bash_status.py", bash_payload("bun test x", 1), repo, tmp_path)
        assert marker(tmp_path)["red"] is True


class TestStopGate:
    def stop_payload(self, session="sess-1", active=False):
        return {"session_id": session, "cwd": ".", "stop_hook_active": active}

    def test_red_marker_blocks_naming_command(self, tmp_path):
        repo, _g = repo_with_story(tmp_path)
        run_script("bash_status.py", bash_payload("pytest -q tests/test_x.py", 1), repo, tmp_path)
        r = run_script("stop_gate.py", self.stop_payload(), repo, tmp_path)
        out = json.loads(r.stdout)
        assert out["decision"] == "block" and "test_x" in out["reason"]

    def test_stop_hook_active_never_blocks(self, tmp_path):
        repo, _g = repo_with_story(tmp_path)
        run_script("bash_status.py", bash_payload("pytest -q tests/test_x.py", 1), repo, tmp_path)
        r = run_script("stop_gate.py", self.stop_payload(active=True), repo, tmp_path)
        assert r.returncode == 0 and "block" not in r.stdout

    def test_green_or_absent_marker_no_block(self, tmp_path):
        repo, _g = repo_with_story(tmp_path)
        r = run_script("stop_gate.py", self.stop_payload(), repo, tmp_path)
        assert "block" not in r.stdout
        run_script("bash_status.py", bash_payload("pytest -q tests/test_x.py", 0), repo, tmp_path)
        r = run_script("stop_gate.py", self.stop_payload(), repo, tmp_path)
        assert "block" not in r.stdout

    def test_stale_digest_nudges_without_blocking(self, tmp_path):
        repo, g = repo_with_story(tmp_path)
        old = g("rev-parse", "--short", "HEAD").stdout.strip()
        (tmp_path / "xp").mkdir()
        (tmp_path / "xp" / "session.md").write_text(f"# Session digest — written x at {old}\n")
        (repo / "f.py").write_text("A = 2\n")
        g("add", "-A")
        g("commit", "-qm", "newer")
        r = run_script("stop_gate.py", self.stop_payload(), repo, tmp_path)
        assert "block" not in r.stdout and "digest" in r.stdout

    def test_fresh_digest_no_nudge(self, tmp_path):
        repo, g = repo_with_story(tmp_path)
        head = g("rev-parse", "--short", "HEAD").stdout.strip()
        (tmp_path / "xp").mkdir()
        (tmp_path / "xp" / "session.md").write_text(f"# Session digest — written x at {head}\n")
        r = run_script("stop_gate.py", self.stop_payload(), repo, tmp_path)
        assert "digest" not in r.stdout and "block" not in r.stdout


class TestRegistration:
    def test_hooks_json_registers_both(self):
        cfg = json.loads(HOOKS_JSON.read_text())
        stop = [h["command"] for e in cfg["hooks"]["Stop"] for h in e["hooks"]]
        post = [
            h["command"]
            for e in cfg["hooks"]["PostToolUse"]
            for h in e["hooks"]
            if e.get("matcher") == "Bash"
        ]
        assert any("stop_gate.py" in c for c in stop)
        assert any("bash_status.py" in c for c in post)
