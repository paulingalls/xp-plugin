#!/usr/bin/env python3
import os
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path

CLOSE = Path(__file__).parents[2] / "plugins" / "xp-plugin" / "scripts" / "close.py"


with tempfile.TemporaryDirectory() as folder:
    root = Path(folder)
    repo = root / "repo"
    data = root / "data"
    repo.mkdir()
    data.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)

    sentinel = root / "condition-ran"
    condition = root / "condition.py"
    condition.write_text(f"from pathlib import Path\nPath({str(sentinel)!r}).write_text('green')\n")
    command = shlex.join([sys.executable, str(condition)])
    plan = data / "plan.md"
    plan.write_text(
        "# plan\n"
        "## Milestone 11   [in-progress]\n"
        f"Done when: {command}\n"
        "### Sprint 9\n"
        "#### story-129 — dry-run preview   [done]\n"
    )
    before = plan.read_bytes()
    env = os.environ.copy()
    env["XP_DATA"] = str(data)
    env.pop("XP_ROLE", None)

    result = subprocess.run(
        [sys.executable, str(CLOSE), "sprint", "9", "milestone-done", "--dry-run"],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
    )

    if not sentinel.exists():
        raise SystemExit(
            "RED: falsifier never reached the milestone Done when: command; "
            f"rc={result.returncode}, stderr={result.stderr.strip()!r}"
        )
    if result.returncode != 0:
        raise SystemExit(f"RED: milestone preview refused: {result.stderr.strip()}")
    if plan.read_bytes() != before:
        raise SystemExit("RED: milestone-done --dry-run changed plan.md")
    if "milestone ready:" not in result.stdout or "status unchanged" not in result.stdout:
        verdict = result.stdout.strip()
        raise SystemExit(f"RED: milestone preview did not report its verdict: {verdict!r}")
    print("GREEN: milestone-done dry-run ran its condition and left plan.md byte-identical")
