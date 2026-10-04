import io
import json
import os
import subprocess
import sys

import pytest
from xpcore import launch

FAKE_CLAUDE = """\
import json, os, sys
prompt = sys.stdin.read()
print(json.dumps({"type": "system", "subtype": "init", "session_id": "sess-1"}), flush=True)
print("not json", flush=True)
print(json.dumps({"type": "assistant", "message": {"content": [{"type": "text"}]}}), flush=True)
env = {k: os.environ[k] for k in ("XP_ROLE", "XP_STORY_ID", "XP_HARNESS")}
if prompt != "silent":
    print(json.dumps({"type": "result", "num_turns": 2, "duration_ms": 3000,
                      "total_cost_usd": 0.5, "result": json.dumps([prompt, env])}))
"""
FAKE_CODEX = """\
import json, sys
prompt = sys.stdin.read()
print(json.dumps({"type": "thread.started", "thread_id": "th-1"}), flush=True)
for text in ("draft", json.dumps([prompt, sys.argv[1:]])):
    item = {"type": "agent_message", "text": text}
    print(json.dumps({"type": "item.completed", "item": item}), flush=True)
"""


@pytest.fixture
def project(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    (root / ".xp").mkdir(parents=True)
    (root / ".xp" / "config.yml").write_text(
        "roles:\n  executor: claude/sonnet/high\n  reviewer: codex/gpt-6\n"
    )
    for args in (["init", "-q", "-b", "main"], ["add", "-A"]):
        subprocess.run(["git", *args], cwd=root, check=True)
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@e", "commit", "-qm", "i"],
        cwd=root,
        check=True,
    )
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, body in (("claude", FAKE_CLAUDE), ("codex", FAKE_CODEX)):
        (bin_dir / name).write_text(f"#!{sys.executable}\n{body}")
        (bin_dir / name).chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("XP_DATA", str(tmp_path / "data"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.chdir(root)
    return root


def test_claude_argv():
    argv = launch.agent_argv("claude", "opus", "high")
    assert argv[:2] == ["claude", "-p"] and "--dangerously-skip-permissions" in argv
    assert argv[argv.index("--output-format") + 1] == "stream-json" and "--verbose" in argv
    assert argv[-4:] == ["--model", "opus", "--effort", "high"]
    assert "--effort" not in launch.agent_argv("claude", "opus", "")


def test_codex_argv(tmp_path, monkeypatch):
    monkeypatch.setenv("XP_DATA", str(tmp_path))
    argv = launch.agent_argv("codex", "gpt-6", "medium")
    joined = " ".join(argv)
    for pin in ("inherit=all", "exclude=[]", "include_only=[]"):
        assert f"-c shell_environment_policy.{pin}" in joined
    assert f"--sandbox danger-full-access --add-dir {tmp_path}" in joined
    assert "-m gpt-6 -c model_reasoning_effort=medium" in joined and argv[-1] == "-"
    assert "workspace-write" in launch.sandbox_line(
        launch.agent_argv("codex", "m", "", "workspace-write")
    )
    assert launch.sandbox_line(launch.agent_argv("claude", "m", "")) == ""


def test_codex_widening_only_for_linked_worktrees(project, tmp_path):
    assert launch.codex_widening(project) == []
    tree = tmp_path / "wt"
    subprocess.run(["git", "worktree", "add", "-q", "-b", "s", str(tree)], cwd=project, check=True)
    assert launch.codex_widening(tree) == ["--add-dir", str((project / ".git").resolve())]


def test_parsers():
    echo, result = launch.parse_claude('{"type":"result","is_error":true,"num_turns":1}')
    assert echo == "[result] error 1 turns" and result["is_error"]
    assert launch.parse_claude("plain text") == (None, None)
    echo, result = launch.parse_codex('{"type":"item.completed","item":{"type":"reasoning"}}')
    assert echo == "[item.completed] reasoning" and result is None


def test_tee_survives_a_failing_log(tmp_path):
    class Broken(io.StringIO):
        def write(self, text):
            raise OSError("disk full")

    out = []
    lines = ['{"type":"system","session_id":"s"}\n', '{"type":"result","result":"done"}\n']
    result = launch.tee(lines, Broken(), out.append, "claude", tmp_path)
    assert result["result"] == "done"
    assert out[0].startswith("warning: log write failed") and out[-1].startswith("[result] ok")


def test_missing_harness_names_the_install(monkeypatch, tmp_path):
    monkeypatch.setenv("PATH", str(tmp_path))
    assert "npm i -g @openai/codex" in launch.missing_harness("codex")


def test_run_agent_claude_streams_tees_and_returns_result(project, tmp_path, capsys):
    proc = launch.run_agent("executor", "do the thing", project, "story-007-executor")
    assert proc.returncode == 0
    prompt, env = json.loads(proc.stdout)
    assert prompt == "do the thing"
    assert env == {"XP_ROLE": "executor", "XP_STORY_ID": "story-007", "XP_HARNESS": "claude"}
    out = capsys.readouterr().out
    assert "[system] init" in out and "[result] ok 2 turns 3s $0.50" in out
    log = (tmp_path / "data" / "logs" / "story-007-executor.log").read_text()
    assert log.startswith("===== story-007-executor executor claude/sonnet")
    assert "not json\n" in log and log.count("transcript: ") == 1
    assert "sess-1.jsonl" in log


def test_run_agent_without_result_fails(project):
    proc = launch.run_agent("executor", "silent", project, "story-007-executor")
    assert proc.returncode == 1 and proc.stdout == "" and "story-007-executor.log" in proc.stderr


def test_run_agent_codex_takes_last_message_and_widens(project, tmp_path, capsys):
    tree = tmp_path / "wt"
    subprocess.run(["git", "worktree", "add", "-q", "-b", "s", str(tree)], cwd=project, check=True)
    proc = launch.run_agent("reviewer", "look", tree, "x", env={"XP_STORY_ID": "story-9"})
    prompt, argv = json.loads(proc.stdout)
    assert proc.returncode == 0 and prompt == "look"
    assert argv[-3:] == ["--add-dir", str((project / ".git").resolve()), "-"]
    assert "codex sandbox: danger-full-access" in capsys.readouterr().err
    assert "(not written yet)" in (tmp_path / "data" / "logs" / "x.log").read_text()
