"""Supported card edits in disposable consumers."""

import os
import re
import subprocess
import sys
from pathlib import Path

from close_helpers import PLUGIN


def plugin():
    return Path(os.environ.get("XP_ADJUSTMENT_PLUGIN", str(PLUGIN)))


def command(repo, env, script, *args):
    return subprocess.run(
        [sys.executable, str(plugin() / "scripts" / script), *args],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
    )


def adjust(repo, env, replacements, context="executor"):
    root = Path(env["XP_DATA"])
    candidate = root / "adjustment.md"
    candidate.unlink(missing_ok=True)
    result = command(repo, env, "work.py", "card-snapshot", "story-042", str(candidate))
    assert result.returncode == 0, result.stderr
    digest = re.search(r"^digest: (\w+)$", result.stdout, re.M).group(1)
    status = re.search(r"^status: (.+)$", result.stdout, re.M).group(1)
    text = candidate.read_text()
    for old, new in replacements:
        assert old in text
        text = text.replace(old, new)
    candidate.write_text(text)
    result = command(
        repo,
        env,
        "work.py",
        "edit-card",
        "story-042",
        "--context",
        context,
        "--digest",
        digest,
        "--status",
        status,
        str(candidate),
    )
    assert result.returncode == 0, result.stderr
    return candidate
