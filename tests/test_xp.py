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


ROUTES = {
    "story story-001": "xpcore.story.cmd_story",
    "story review story-001": "xpcore.story.cmd_story_review",
    "story land story-001": "xpcore.land.cmd_story_land",
    "free typo": "xpcore.story.cmd_free",
    "free land typo": "xpcore.land.cmd_free_land",
    "free post-merge typo": "xpcore.land.cmd_free_post_merge",
    "sprint post-merge 12": "xpcore.sprint.cmd_sprint_post_merge",
    "note a b": "xpcore.records.cmd_note",
    "recover": "xpcore.session.cmd_recover",
}


@pytest.mark.parametrize("command", ROUTES)
def test_routes(command):
    import xp

    parser = xp.build()
    args = parser.parse_args(command.split())
    xp.route(parser, args)
    assert args.run.target == ROUTES[command]
    if command.split()[0] in ("story", "free", "sprint"):
        assert args.id == command.split()[-1]
