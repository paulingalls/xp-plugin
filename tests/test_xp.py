import subprocess
import sys
from pathlib import Path

import pytest

XP = Path(__file__).parent.parent / "plugins" / "xp-plugin" / "scripts" / "xp.py"
COMMANDS = ["", "setup", "session-start", "recover", "sprint", "story", "free"]
COMMANDS += ["bug", "debt", "note", "resolve"]


@pytest.mark.parametrize("command", COMMANDS)
def test_every_command_answers_help_without_running(command, tmp_path):
    argv = [sys.executable, str(XP), *command.split(), "--help"]
    proc = subprocess.run(argv, cwd=tmp_path, capture_output=True, text=True)
    assert proc.returncode == 0 and proc.stdout.startswith("usage: xp.py")


def test_unknown_story_action_is_a_usage_error(tmp_path):
    argv = [sys.executable, str(XP), "story", "bogus", "story-001"]
    proc = subprocess.run(argv, cwd=tmp_path, capture_output=True, text=True)
    assert proc.returncode == 2 and "unknown story action" in proc.stderr
