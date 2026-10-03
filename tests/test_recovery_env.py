"""Explicit recovery preserves durable pointers and unreadable saved state."""

import json
import os
import shutil
import subprocess
import sys

import pytest
from session_start_helpers import HOOK, xp_repo


def recover(repo, data, plugin, role="lead", hook=False):
    env = os.environ | {"XP_DATA": str(data)}
    env.pop("XP_ROLE", None)
    if role is not None:
        env["XP_ROLE"] = role
    return subprocess.run(
        [sys.executable, str(plugin / "scripts/session_start.py"), *([] if hook else ["recover"])],
        input='{"session_id":"recovery"}',
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
    )


def fixture(tmp_path):
    repo, _git = xp_repo(tmp_path)
    data = tmp_path / "data"
    data.mkdir()
    plugin = tmp_path / "durable"
    shutil.copytree(HOOK.parent.parent, plugin)
    return repo, data, plugin


@pytest.mark.parametrize("hook", [False, True])
@pytest.mark.parametrize("field", ["plugin_root", "plugin_version", "missing"])
def test_lead_refreshes_each_field_and_preserves_unrelated_keys(tmp_path, hook, field):
    repo, data, plugin = fixture(tmp_path)
    version = json.loads((plugin / ".claude-plugin/plugin.json").read_text())["version"]
    path = data / "env.json"
    expected = {"plugin_root": str(plugin), "plugin_version": version}
    if field != "missing":
        saved = expected | {"scratch": "kept", field: "stale"}
        path.write_text(json.dumps(saved))
        expected["scratch"] = "kept"
    result = recover(repo, data, plugin, hook=hook)
    assert result.returncode == 0, result.stderr
    assert json.loads(path.read_text()) == expected


@pytest.mark.parametrize("role", ["teammate", "reviewer", "plan-reviewer", "arbitrary", ""])
def test_nonlead_never_refreshes(tmp_path, role):
    repo, data, plugin = fixture(tmp_path)
    path = data / "env.json"
    body = b'{ "plugin_root": "/old", "plugin_version": "0.0.0" }\n\n'
    path.write_bytes(body)
    assert recover(repo, data, plugin, role=role).returncode == 0
    assert path.read_bytes() == body


@pytest.mark.parametrize("body", [b"[1,2]\n", b"not json\n", b"\xff"])
def test_unreadable_env_remains_distinct_from_missing(tmp_path, body):
    repo, data, plugin = fixture(tmp_path)
    path = data / "env.json"
    path.write_bytes(body)
    result = recover(repo, data, plugin)
    assert result.returncode == 0
    assert "refresh FAILED" in result.stdout
    assert path.read_bytes() == body


def test_directory_env_is_visible_and_not_overwritten(tmp_path):
    repo, data, plugin = fixture(tmp_path)
    path = data / "env.json"
    path.mkdir()
    result = recover(repo, data, plugin)
    assert "refresh FAILED" in result.stdout and path.is_dir()


def test_current_pair_avoids_a_write(tmp_path):
    repo, data, plugin = fixture(tmp_path)
    assert recover(repo, data, plugin).returncode == 0
    path = data / "env.json"
    known = 1_600_000_000_123_456_789
    os.utime(path, ns=(known, known))
    assert recover(repo, data, plugin).returncode == 0
    assert path.stat().st_mtime_ns == known


@pytest.mark.parametrize("role", [None, "lead"])
@pytest.mark.parametrize("hook", [False, True])
def test_worktree_copy_never_becomes_durable_pointer(tmp_path, role, hook):
    repo, data, plugin = fixture(tmp_path)
    assert recover(repo, data, plugin).returncode == 0
    path = data / "env.json"
    before = path.read_bytes()
    doomed = data / "worktrees/story-000/plugins/xp-plugin"
    shutil.copytree(plugin, doomed)
    result = recover(repo, data, doomed, role=role, hook=hook)
    assert result.returncode == 0 and result.stdout
    assert path.read_bytes() == before


def test_unknown_manifest_never_pins_unknown_version(tmp_path):
    repo, data, plugin = fixture(tmp_path)
    assert recover(repo, data, plugin).returncode == 0
    before = (data / "env.json").read_bytes()
    (plugin / ".claude-plugin/plugin.json").write_text("not json")
    result = recover(repo, data, plugin)
    assert "refresh FAILED" in result.stdout
    assert (data / "env.json").read_bytes() == before
