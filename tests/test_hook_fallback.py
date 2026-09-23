import json
import os
import shlex
import subprocess
from pathlib import Path

import pytest

HOOKS = Path(__file__).parent.parent / "plugins" / "xp-plugin" / "hooks" / "hooks.json"
SCRIPTS = {
    "SessionStart": "session_start.py",
    "PostToolUse": "bash_status.py",
    "Stop": "stop_gate.py",
    "PostToolUseFailure": "bash_status.py",
}


def commands():
    hooks = json.loads(HOOKS.read_text())["hooks"]
    pairs = [
        (event, hook["command"])
        for event, entries in hooks.items()
        for entry in entries
        for hook in entry["hooks"]
    ]
    assert len(pairs) == len(SCRIPTS)
    return dict(pairs)


def script(root, name, stdout, status):
    path = root / "scripts" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "import sys\n"
        "data = sys.stdin.buffer.read()\n"
        f"sys.stdout.buffer.write({stdout!r})\n"
        f"sys.exit({status} if data == b'input\\x00bytes' else 99)\n"
    )


def run(command, root, payload=b"input\x00bytes"):
    return subprocess.run(
        command,
        input=payload,
        capture_output=True,
        shell=True,
        executable="/bin/sh",
        env=os.environ | {"CLAUDE_PLUGIN_ROOT": str(root)},
    )


@pytest.mark.parametrize("event", SCRIPTS)
def test_deleted_root_runs_sibling_with_streams_and_status(tmp_path, event):
    name = SCRIPTS[event]
    gone = tmp_path / "0.23.9"
    new = tmp_path / "0.23.10"
    output = b'{"decision": "block"}\n' if event == "Stop" else b"context\n"
    script(new, name, output, 23)

    result = run(commands()[event], gone)

    assert result.stdout == output
    assert result.returncode == 23
    assert str(gone).encode() in result.stderr
    assert str(new).encode() in result.stderr


def test_numeric_newest_sibling_with_script_wins(tmp_path):
    gone = tmp_path / "0.23.1"
    script(tmp_path / "0.23.2", "stop_gate.py", b"wrong", 2)
    script(tmp_path / "0.23.10", "stop_gate.py", b"right", 10)
    script(tmp_path / "0.24.0", "bash_status.py", b"incomplete", 24)

    result = run(commands()["Stop"], gone)

    assert result.stdout == b"right"
    assert result.returncode == 10
    assert b"0.23.10" in result.stderr


def test_no_usable_sibling_is_advisory(tmp_path):
    gone = tmp_path / "0.23.1"
    script(tmp_path / "0.23.2", "bash_status.py", b"unrelated", 2)

    result = run(commands()["Stop"], gone)

    assert result.returncode == 0
    assert result.stdout == b""
    assert str(gone).encode() in result.stderr


@pytest.mark.parametrize("script_present", [True, False])
def test_intact_root_never_switches(script_present, tmp_path):
    pinned = tmp_path / "0.23.1"
    pinned.mkdir()
    if script_present:
        script(pinned, "stop_gate.py", b"pinned", 7)
    script(tmp_path / "0.23.2", "stop_gate.py", b"sibling", 8)

    result = run(commands()["Stop"], pinned)

    if script_present:
        assert result.stdout == b"pinned"
        assert result.returncode == 7
        assert result.stderr == b""
    else:
        assert result.returncode == 0
        assert result.stdout == b""
        assert str(pinned).encode() in result.stderr


def test_all_four_commands_share_one_launcher():
    actual = commands()
    assert set(actual) == set(SCRIPTS)
    normalized = []
    for event, command in actual.items():
        words = shlex.split(command)
        assert words[-1] == SCRIPTS[event]
        normalized.append(command.removesuffix(SCRIPTS[event]))
    assert len(set(normalized)) == 1
