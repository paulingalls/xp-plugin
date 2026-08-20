"""story-004: Stop advisory gate + bash test-status leg.

Verify: pytest -q tests/test_stop_gate.py
Payload shapes are from LIVE captures (Claude Code 2.1.237): failing Bash fires
PostToolUseFailure with top-level `error: "Exit code N\\n..."` and no
tool_response; successful PostToolUse's tool_response has NO exit_code.
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


class TestBashStatus:
    def test_failure_event_records_red_then_success_greens(self, tmp_path):
        repo, _g = repo_with_story(tmp_path)
        payload = failure_payload("cd x && pytest -q tests/test_x.py")
        run_script("bash_status.py", payload, repo, tmp_path)
        assert [m["red"] for m in markers(tmp_path)] == [True]
        run_script("bash_status.py", success_payload("pytest -q tests/test_x.py"), repo, tmp_path)
        assert [m["red"] for m in markers(tmp_path)] == [False]

    def test_non_verify_failure_writes_nothing(self, tmp_path):
        repo, _g = repo_with_story(tmp_path)
        run_script("bash_status.py", failure_payload("pytest -q tests/other.py"), repo, tmp_path)
        assert markers(tmp_path) == []

    def test_non_exit_failure_writes_nothing(self, tmp_path):
        repo, _g = repo_with_story(tmp_path)
        p = failure_payload("pytest -q tests/test_x.py", error="Permission denied by user")
        run_script("bash_status.py", p, repo, tmp_path)
        assert markers(tmp_path) == []

    def test_mention_in_exit_zero_command_does_not_green(self, tmp_path):
        repo, _g = repo_with_story(tmp_path)
        run_script("bash_status.py", failure_payload("pytest -q tests/test_x.py"), repo, tmp_path)
        mention = success_payload("git commit -m 'red: pytest -q tests/test_x.py still failing'")
        run_script("bash_status.py", mention, repo, tmp_path)
        assert [m["red"] for m in markers(tmp_path)] == [True]  # mention is not invocation

    def test_success_masking_never_greens_a_red(self, tmp_path):
        repo, _g = repo_with_story(tmp_path)
        run_script("bash_status.py", failure_payload("pytest -q tests/test_x.py"), repo, tmp_path)
        for masked in (
            "pytest -q tests/test_x.py 2>&1 | tail -5",
            "pytest -q tests/test_x.py; echo done",
            "pytest -q tests/test_x.py || true",
            "pytest -q tests/test_x.py::test_one",
        ):
            run_script("bash_status.py", success_payload(masked), repo, tmp_path)
            assert [m["red"] for m in markers(tmp_path)] == [True], f"greened by: {masked}"

    def test_exact_verify_with_and_chain_greens(self, tmp_path):
        repo, _g = repo_with_story(tmp_path)
        run_script("bash_status.py", failure_payload("pytest -q tests/test_x.py"), repo, tmp_path)
        ok = success_payload("pytest -q tests/test_x.py && git push")
        run_script("bash_status.py", ok, repo, tmp_path)
        assert [m["red"] for m in markers(tmp_path)] == [False]

    def test_multiline_command_failure_records_red(self, tmp_path):
        repo, _g = repo_with_story(tmp_path)
        p = failure_payload("cd sub\npytest -q tests/test_x.py")
        run_script("bash_status.py", p, repo, tmp_path)
        assert [m["red"] for m in markers(tmp_path)] == [True]

    def test_matches_any_in_progress_story_with_per_verify_markers(self, tmp_path):
        repo, _g = repo_with_story(tmp_path)
        plan = repo / ".xp" / "plan.md"
        plan.write_text(
            plan.read_text() + "#### story-043 — other   [in-progress]\nVerify: bun test x\n"
        )
        run_script("bash_status.py", failure_payload("pytest -q tests/test_x.py"), repo, tmp_path)
        run_script("bash_status.py", success_payload("bun test x"), repo, tmp_path)
        reds = sorted(m["red"] for m in markers(tmp_path))
        assert reds == [False, True]  # two markers: B's green cannot hide A's red


class TestStopGate:
    def stop_payload(self, session="sess-1", active=False):
        return {"session_id": session, "cwd": ".", "stop_hook_active": active}

    def _red(self, repo, tmp_path):
        run_script("bash_status.py", failure_payload("pytest -q tests/test_x.py"), repo, tmp_path)

    def test_red_marker_blocks_naming_command(self, tmp_path):
        repo, _g = repo_with_story(tmp_path)
        self._red(repo, tmp_path)
        r = run_script("stop_gate.py", self.stop_payload(), repo, tmp_path)
        out = json.loads(r.stdout)
        assert out["decision"] == "block" and "test_x" in out["reason"]

    def test_any_red_blocks_despite_other_green(self, tmp_path):
        repo, _g = repo_with_story(tmp_path)
        plan = repo / ".xp" / "plan.md"
        plan.write_text(
            plan.read_text() + "#### story-043 — other   [in-progress]\nVerify: bun test x\n"
        )
        self._red(repo, tmp_path)
        run_script("bash_status.py", success_payload("bun test x"), repo, tmp_path)
        r = run_script("stop_gate.py", self.stop_payload(), repo, tmp_path)
        assert json.loads(r.stdout)["decision"] == "block"

    def test_stop_hook_active_never_blocks(self, tmp_path):
        repo, _g = repo_with_story(tmp_path)
        self._red(repo, tmp_path)
        r = run_script("stop_gate.py", self.stop_payload(active=True), repo, tmp_path)
        assert r.returncode == 0 and "block" not in r.stdout

    def test_red_for_no_longer_in_progress_story_does_not_block(self, tmp_path):
        repo, _g = repo_with_story(tmp_path)
        self._red(repo, tmp_path)
        plan = repo / ".xp" / "plan.md"
        plan.write_text(plan.read_text().replace("[in-progress]", "[done]"))
        r = run_script("stop_gate.py", self.stop_payload(), repo, tmp_path)
        assert "block" not in r.stdout  # deferral via plan status is honest and works

    def test_green_or_absent_marker_no_block(self, tmp_path):
        repo, _g = repo_with_story(tmp_path)
        r = run_script("stop_gate.py", self.stop_payload(), repo, tmp_path)
        assert "block" not in r.stdout
        run_script("bash_status.py", success_payload("pytest -q tests/test_x.py"), repo, tmp_path)
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

    def test_stampless_digest_nudges(self, tmp_path):
        repo, _g = repo_with_story(tmp_path)
        (tmp_path / "xp").mkdir()
        (tmp_path / "xp" / "session.md").write_text("no stamp\n")
        r = run_script("stop_gate.py", self.stop_payload(), repo, tmp_path)
        assert "digest" in r.stdout

    def test_no_in_progress_story_no_nudge(self, tmp_path):
        repo, g = repo_with_story(tmp_path)
        plan = repo / ".xp" / "plan.md"
        plan.write_text(plan.read_text().replace("[in-progress]", "[done]"))
        old = g("rev-parse", "--short", "HEAD").stdout.strip()
        (tmp_path / "xp").mkdir()
        (tmp_path / "xp" / "session.md").write_text(f"# Session digest — written x at {old}old\n")
        r = run_script("stop_gate.py", self.stop_payload(), repo, tmp_path)
        assert "digest" not in r.stdout

    def test_fresh_digest_no_nudge(self, tmp_path):
        repo, g = repo_with_story(tmp_path)
        head = g("rev-parse", "--short", "HEAD").stdout.strip()
        (tmp_path / "xp").mkdir()
        (tmp_path / "xp" / "session.md").write_text(f"# Session digest — written x at {head}\n")
        r = run_script("stop_gate.py", self.stop_payload(), repo, tmp_path)
        assert "digest" not in r.stdout and "block" not in r.stdout

    def test_empty_session_md_is_stampless_hence_nudges(self, tmp_path):
        repo, _g = repo_with_story(tmp_path)
        (tmp_path / "xp").mkdir()
        (tmp_path / "xp" / "session.md").write_text("")
        r = run_script("stop_gate.py", self.stop_payload(), repo, tmp_path)
        assert r.returncode == 0 and "digest" in r.stdout


class TestRegistration:
    def test_hooks_json_registers_all_three_legs(self):
        cfg = json.loads(HOOKS_JSON.read_text())
        stop = [h["command"] for e in cfg["hooks"]["Stop"] for h in e["hooks"]]
        post = [
            h["command"]
            for e in cfg["hooks"]["PostToolUse"]
            for h in e["hooks"]
            if e.get("matcher") == "Bash"
        ]
        post_fail = [
            h["command"]
            for e in cfg["hooks"].get("PostToolUseFailure", [])
            for h in e["hooks"]
            if e.get("matcher") == "Bash"
        ]
        assert any("stop_gate.py" in c for c in stop)
        assert any("bash_status.py" in c for c in post)
        assert any("bash_status.py" in c for c in post_fail)
