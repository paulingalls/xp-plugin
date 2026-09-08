"""Falsifier: a hook run from a WORKTREE copy with XP_ROLE unset repins the lead
to a directory that story close deletes.

stop_gate.py:23 is `os.environ.get("XP_ROLE", "lead")`, so an ABSENT role is read
as lead — constraint 15's "never infer one state only from the absence of another".
SessionStart has made that same default since story-126 and it was cheap there: it
runs once per session. v0.22.1 gave the default a PER-TURN WRITER. Reds while an
unset role lets a non-durable plugin root become the recorded pin; greens when an
absent role is treated as unknown rather than as lead.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).parents[2]
DURABLE = REPO / "plugins" / "xp-plugin"

with tempfile.TemporaryDirectory() as tmp:
    data, throwaway = Path(tmp) / "data", Path(tmp) / "throwaway"
    data.mkdir()
    # a plugin copy standing in for a worktree's: real, and about to be deleted
    shutil.copytree(DURABLE, throwaway / "plugins" / "xp-plugin")
    repo = Path(tmp) / "repo"
    (repo / ".xp").mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    (data / "env.json").write_text(
        json.dumps({"plugin_root": str(DURABLE), "plugin_version": "0.0.0"}) + "\n"
    )
    env = {k: v for k, v in os.environ.items() if k != "XP_ROLE"}
    env |= {"XP_DATA": str(data), "HOME": tmp}
    hook = throwaway / "plugins" / "xp-plugin" / "scripts" / "stop_gate.py"
    run = subprocess.run(
        [sys.executable, str(hook)],
        input=json.dumps({"session_id": "falsifier"}),
        capture_output=True,
        text=True,
        env=env,
        cwd=repo,
    )
    recorded = json.loads((data / "env.json").read_text()).get("plugin_root", "")
    reached = "not inside a git repository" not in run.stderr

if not reached:  # a hook that never ran greens on an unrelated refusal
    print(f"falsifier never reached repoint_env: {run.stderr.strip()!r}", file=sys.stderr)
    sys.exit(1)
if str(throwaway) not in recorded:
    sys.exit(0)
print(f"an unset XP_ROLE repinned the lead to a throwaway root: {recorded}", file=sys.stderr)
sys.exit(1)
