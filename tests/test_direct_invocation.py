"""Directly runnable scripts either dispatch intentionally or refuse explicitly."""

import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

PLUGIN = Path(__file__).parent.parent / "plugins" / "xp-plugin"
SCRIPTS = PLUGIN / "scripts"


def hook_scripts():
    hooks = json.loads((PLUGIN / "hooks" / "hooks.json").read_text())["hooks"]
    commands = (
        hook["command"]
        for groups in hooks.values()
        for group in groups
        for hook in group["hooks"]
        if hook["type"] == "command"
    )
    return {Path(shlex.split(command)[-1]).name for command in commands}


HOOK_SCRIPTS = hook_scripts()
DIRECTLY_RUNNABLE = sorted(
    path
    for path in SCRIPTS.rglob("*.py")
    if path.read_text().splitlines()[0].startswith("#!") and path.name not in HOOK_SCRIPTS
)


def invoke(path, tmp_path):
    return subprocess.run(
        [sys.executable, str(path), "nothing-names-this"],
        cwd=tmp_path,
        env=os.environ | {"XP_DATA": str(tmp_path / "data")},
        capture_output=True,
        text=True,
    )


def test_the_derived_class_has_a_nonzero_floor():
    assert len(DIRECTLY_RUNNABLE) >= 11


@pytest.mark.parametrize("path", DIRECTLY_RUNNABLE, ids=lambda path: path.stem)
def test_a_directly_runnable_script_does_not_succeed_silently(path, tmp_path):
    assert invoke(path, tmp_path).returncode != 0


def test_sprint_close_names_its_real_entry_point(tmp_path):
    result = invoke(SCRIPTS / "sprint_close.py", tmp_path)
    assert "close.py sprint <id> <action>" in result.stderr
