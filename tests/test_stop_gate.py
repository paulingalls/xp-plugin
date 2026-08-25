"""story-004: Stop advisory gate + bash test-status leg.

Verify: pytest -q tests/test_stop_gate.py
Payload shapes are from LIVE captures (Claude Code 2.1.237): failing Bash fires
PostToolUseFailure with top-level `error: "Exit code N\\n..."` and no
tool_response; successful PostToolUse's tool_response has NO exit_code.
"""

import json
import os
import pty
import shutil
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


class TestStopGate:
    def stop_payload(self, session="sess-1", active=False):
        return {"session_id": session, "cwd": ".", "stop_hook_active": active}

    def _red(self, repo, tmp_path):
        run_script("bash_status.py", failure_payload("pytest -q tests/test_x.py"), repo, tmp_path)

    def test_a_pipe_keeps_the_existing_empty_output_contract(self, tmp_path):
        repo, _g = repo_with_story(tmp_path)
        result = run_script("stop_gate.py", self.stop_payload(), repo, tmp_path)
        assert (result.returncode, result.stdout, result.stderr) == (0, "", "")

    def test_malformed_payload_is_advisory_but_visible(self, tmp_path):
        repo, _g = repo_with_story(tmp_path)
        result = subprocess.run(
            [sys.executable, str(SCRIPTS / "stop_gate.py")],
            input="not json",
            env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path), "XP_DATA": str(tmp_path / "xp")},
            cwd=repo,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0 and result.stdout == ""
        assert "JSONDecodeError" in result.stderr

    def test_a_tty_names_the_hook_and_its_json_input(self):
        master, slave = pty.openpty()
        try:
            result = subprocess.run(
                [sys.executable, str(SCRIPTS / "stop_gate.py")],
                stdin=slave,
                capture_output=True,
                text=True,
                timeout=1,
            )
        finally:
            os.close(master)
            os.close(slave)
        assert result.returncode == 0
        assert all(word in result.stdout for word in ("stop_gate.py", "JSON", "stdin"))

    def test_red_marker_blocks_naming_command(self, tmp_path):
        repo, _g = repo_with_story(tmp_path)
        self._red(repo, tmp_path)
        r = run_script("stop_gate.py", self.stop_payload(), repo, tmp_path)
        out = json.loads(r.stdout)
        assert out["decision"] == "block" and "test_x" in out["reason"]

    def test_any_red_blocks_despite_other_green(self, tmp_path):
        repo, _g = repo_with_story(tmp_path)
        plan = tmp_path / "xp" / "plan.md"
        plan.write_text(
            plan.read_text() + "#### story-043 — other   [in-progress]\nVerify: bun test x\n"
        )
        self._red(repo, tmp_path)
        run_script("bash_status.py", success_payload("bun test x"), repo, tmp_path)
        r = run_script("stop_gate.py", self.stop_payload(), repo, tmp_path)
        assert json.loads(r.stdout)["decision"] == "block"

    def test_stop_hook_active_never_blocks(self, tmp_path):
        """Over the codex flip pattern too: 0.147.0 was measured flipping on the
        SECOND firing, and the card carries a three-firing sighting — the gate must
        release on the flag alone, never on a count of its own blocks.
        """
        repo, _g = repo_with_story(tmp_path)
        self._red(repo, tmp_path)
        for active in (False, False, True):
            r = run_script("stop_gate.py", self.stop_payload(active=active), repo, tmp_path)
            assert r.returncode == 0
            assert ("block" in r.stdout) is not active

    def test_red_for_no_longer_in_progress_story_does_not_block(self, tmp_path):
        repo, _g = repo_with_story(tmp_path)
        self._red(repo, tmp_path)
        plan = tmp_path / "xp" / "plan.md"
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

    def test_no_nudge_ever_stale_digest_or_not(self, tmp_path):
        # the stale-digest nudge was removed: Stop fires per turn, not per session,
        # and the message could only reach the user, not the lead
        repo, g = repo_with_story(tmp_path)
        old = g("rev-parse", "--short", "HEAD").stdout.strip()
        (tmp_path / "xp").mkdir(exist_ok=True)
        (tmp_path / "xp" / "session.md").write_text(f"# Session digest — written x at {old}\n")
        (repo / "f.py").write_text("A = 2\n")
        g("add", "-A")
        g("commit", "-qm", "newer")
        r = run_script("stop_gate.py", self.stop_payload(), repo, tmp_path)
        assert r.returncode == 0 and r.stdout.strip() == ""


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


class TestSprintCloseFindings:
    def test_gate_works_from_repo_subdirectory(self, tmp_path):
        repo, _g = repo_with_story(tmp_path)
        sub = repo / "src"
        sub.mkdir(exist_ok=True)
        p = failure_payload("pytest -q tests/test_x.py")
        subprocess.run(
            [sys.executable, str(SCRIPTS / "bash_status.py")],
            input=json.dumps(p),
            env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path), "XP_DATA": str(tmp_path / "xp")},
            cwd=sub,
            capture_output=True,
            text=True,
        )
        r = subprocess.run(
            [sys.executable, str(SCRIPTS / "stop_gate.py")],
            input=json.dumps({"session_id": "sess-1", "cwd": ".", "stop_hook_active": False}),
            env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path), "XP_DATA": str(tmp_path / "xp")},
            cwd=sub,
            capture_output=True,
            text=True,
        )
        assert json.loads(r.stdout)["decision"] == "block"

    def test_corrupt_marker_does_not_disable_the_gate(self, tmp_path):
        repo, _g = repo_with_story(tmp_path)
        markers_dir = tmp_path / "xp" / "markers"
        markers_dir.mkdir(parents=True)
        (markers_dir / "sess-1.deadbeef.test-status").write_text("{not json")
        run_script("bash_status.py", failure_payload("pytest -q tests/test_x.py"), repo, tmp_path)
        r = run_script("stop_gate.py", self_payload(), repo, tmp_path)
        assert json.loads(r.stdout)["decision"] == "block"  # garbage file cannot hide the red


def self_payload(session="sess-1", active=False):
    return {"session_id": session, "cwd": ".", "stop_hook_active": active}


class TestStoryScopedMarkers:
    """story-008 AC 5: the carried sprint-001 triage input. Keying markers by the
    verify STRING collides across stories that share a Verify command — measured
    on story-002/005, which had byte-identical ones."""

    def two_stories(self, tmp_path, verify_a, verify_b):
        repo, _g = repo_with_story(tmp_path, verify=verify_a)
        plan = tmp_path / "xp" / "plan.md"
        plan.write_text(
            plan.read_text() + f"#### story-043 — other   [in-progress]\nVerify: {verify_b}\n"
        )
        return repo

    def test_identical_verify_commands_get_distinct_markers(self, tmp_path):
        shared = "pytest -q tests/test_shared.py"
        repo = self.two_stories(tmp_path, shared, shared)
        run_script("bash_status.py", failure_payload(shared), repo, tmp_path)
        files = sorted(p.name for p in (tmp_path / "xp" / "markers").glob("*.test-status"))
        assert len(files) == 2, f"one marker for two stories: {files}"
        assert {m["story"] for m in markers(tmp_path)} == {"story-042", "story-043"}

    def test_the_marker_name_carries_the_story_not_a_verify_hash(self, tmp_path):
        """Fault-injection for the key itself: a verify-string hash is identical
        for both stories, so only a story-scoped name can satisfy this."""
        shared = "pytest -q tests/test_shared.py"
        repo = self.two_stories(tmp_path, shared, shared)
        run_script("bash_status.py", failure_payload(shared), repo, tmp_path)
        names = sorted(p.name for p in (tmp_path / "xp" / "markers").glob("*.test-status"))
        assert names == ["sess-1.story-042.test-status", "sess-1.story-043.test-status"]

    def test_distinct_verifies_still_scope_per_story(self, tmp_path):
        repo = self.two_stories(tmp_path, "pytest -q a.py", "bun test x")
        run_script("bash_status.py", failure_payload("pytest -q a.py"), repo, tmp_path)
        run_script("bash_status.py", success_payload("bun test x"), repo, tmp_path)
        by_story = {m["story"]: m["red"] for m in markers(tmp_path)}
        assert by_story == {"story-042": True, "story-043": False}


def codex_post_payload(command, output="", session="sess-1"):
    """Captured from a live codex-cli 0.147.0 session: tool_response is the merged
    output STRING and NO field carries the exit status — `false` returned "" and
    `sh -c 'echo out; echo err 1>&2; exit 3'` returned "err\nout\n". The binary's own
    post-tool-use.command.input schema sets additionalProperties:false, so the absence
    is exhaustive, not a sampling artifact.
    """
    return {
        "session_id": session,
        "turn_id": "turn-1",
        "cwd": ".",
        "hook_event_name": "PostToolUse",
        "model": "gpt-5.6-terra",
        "permission_mode": "bypassPermissions",
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "tool_response": output,
        "tool_use_id": "exec-1",
    }


class TestCodexPayloads:
    """story-025: codex fires PostToolUse for FAILED commands too (the card said it
    fired nothing), so an unproven success must write nothing at all."""

    def test_codex_post_tool_use_writes_no_marker(self, tmp_path):
        repo, _g = repo_with_story(tmp_path)
        codex = codex_post_payload("pytest -q tests/test_x.py")
        run_script("bash_status.py", codex, repo, tmp_path)
        assert markers(tmp_path) == []

    def test_codex_post_tool_use_never_erases_a_red(self, tmp_path):
        """The defect with teeth: a red verify re-run under codex greened its own
        marker and released the gate silently."""
        repo, _g = repo_with_story(tmp_path)
        verify = "pytest -q tests/test_x.py"
        run_script("bash_status.py", failure_payload(verify), repo, tmp_path)
        run_script("bash_status.py", codex_post_payload(verify), repo, tmp_path)
        r = run_script("stop_gate.py", self_payload(), repo, tmp_path)
        assert json.loads(r.stdout)["decision"] == "block"

    def test_a_codex_session_never_inherits_another_sessions_red(self, tmp_path):
        """Why DESIGN calls the Codex Stop gate INERT rather than quiet: markers are
        session-scoped (constraint 10) and no Codex session ever writes one, so a red
        a Claude session planted on the same story is not reachable from here.
        """
        repo, _g = repo_with_story(tmp_path)
        verify = "pytest -q tests/test_x.py"
        run_script("bash_status.py", failure_payload(verify, session="claude-sess"), repo, tmp_path)
        r = run_script("stop_gate.py", self_payload(session="codex-sess"), repo, tmp_path)
        assert r.stdout == ""

    def test_apply_patch_pre_tool_use_is_ignored(self, tmp_path):
        """codex normalises every edit to apply_patch; its patch text is not a command."""
        repo, _g = repo_with_story(tmp_path)
        payload = codex_post_payload("")
        payload.update(
            hook_event_name="PreToolUse",
            tool_name="apply_patch",
            tool_input={"patch": "*** Begin Patch\npytest -q tests/test_x.py\n*** End Patch"},
        )
        del payload["tool_response"]
        r = run_script("bash_status.py", payload, repo, tmp_path)
        assert r.returncode == 0 and r.stderr == "" and markers(tmp_path) == []


class TestACrashIsNotAPass:
    """A hook that dies must still not break the session — but it may not die in
    SILENCE. The blanket `except (Exception, SystemExit): sys.exit(0)` made rc 0
    and empty stderr hold for ANY crash, so every 'the hook ignores this payload'
    assertion in this file passed against a hook that raised on it (measured: 16
    of these 24 tests, this class's own arm included).
    """

    def crashing(self, tmp_path, name):
        """The real script with a raise spliced into main — the defect it must
        survive is an exception, so nothing weaker constructs the condition."""
        broken = tmp_path / name
        text = (SCRIPTS / name).read_text()
        marker = "def main(data: dict) -> int:\n"
        assert marker in text, name
        broken.write_text(text.replace(marker, marker + '    raise ValueError("boom")\n', 1))
        return broken  # its siblings resolve off PYTHONPATH below, not off its new home

    def run(self, tmp_path, name, payload):
        return subprocess.run(
            [sys.executable, str(self.crashing(tmp_path, name))],
            input=json.dumps(payload),
            env={
                "PATH": "/usr/bin:/bin",
                "HOME": str(tmp_path),
                "XP_DATA": str(tmp_path / "xp"),
                "CLAUDE_PLUGIN_ROOT": str(SCRIPTS.parent),
                "PYTHONPATH": str(SCRIPTS),
            },
            cwd=tmp_path,
            capture_output=True,
            text=True,
        )

    def test_every_hook_survives_a_crash_and_says_so(self, tmp_path):
        repo, _g = repo_with_story(tmp_path)
        for name, payload in (
            ("bash_status.py", success_payload("pytest -q tests/test_x.py")),
            ("stop_gate.py", {"session_id": "s", "hook_event_name": "Stop"}),
            ("session_start.py", {"session_id": "s", "hook_event_name": "SessionStart"}),
        ):
            r = self.run(repo, name, payload)
            assert r.returncode == 0, f"{name} broke the session: {r.stderr}"
            assert "ValueError" in r.stderr, f"{name} died in silence"

    def test_every_hook_inherits_the_shared_tty_guard(self, tmp_path):
        scripts = tmp_path / "scripts"
        shutil.copytree(SCRIPTS, scripts)
        env = scripts / "env.py"
        text = env.read_text()
        original = "is a hook; invoke it with a JSON payload on stdin."
        changed = "is a hook; CHANGED shared payload on stdin."
        assert original in text
        env.write_text(text.replace(original, changed, 1))
        for name in ("bash_status.py", "stop_gate.py", "session_start.py"):
            master, slave = pty.openpty()
            try:
                result = subprocess.run(
                    [sys.executable, str(scripts / name)],
                    stdin=slave,
                    capture_output=True,
                    text=True,
                    timeout=1,
                )
            finally:
                os.close(master)
                os.close(slave)
            assert result.returncode == 0, result.stderr
            assert all(word in result.stdout for word in (name, "CHANGED", "stdin"))
