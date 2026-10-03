"""Installed-shape review fixtures, including explicit legacy credentials."""

import json
import shutil
import subprocess
import sys
from pathlib import Path

PLUGIN = Path(__file__).parent.parent / "plugins/xp-plugin"


def installed_launch(tmp_path, mutation=None, relative="scripts/plan_disposition.py"):
    installed = tmp_path / "cache/xp-plugin/fixture"
    shutil.copytree(PLUGIN, installed)
    if mutation:
        path = installed / relative
        source = path.read_text()
        old, new = mutation
        assert old in source
        path.write_text(source.replace(old, new))

    def launch(repo, env, *args):
        return subprocess.run(
            [sys.executable, str(installed / "scripts/spawn.py"), *args],
            cwd=repo,
            env=dict(env, XP_SPAWN_TEST="1"),
            capture_output=True,
            text=True,
        )

    return launch


def legacy_credential(tmp_path):
    path = tmp_path / "data/markers/story-042.ready.json"
    credential = json.loads(path.read_text())
    credential.pop("review_acceptances", None)
    path.write_text(json.dumps(credential))
