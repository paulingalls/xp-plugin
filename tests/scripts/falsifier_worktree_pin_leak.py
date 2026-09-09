"""Falsifier: the per-turn pin writer records a plugin root that story close deletes.

The HARM, not the role. `stop_gate.repoint_env` rewrites env.json every turn, and a
plugin copy inside the data root's `worktrees/` outlives the pin by minutes — close
removes the worktree and env.py then refuses every script with "records plugin_root
<path>, and it is gone". Reds while a worktree-resident root can become the pin;
greens when a non-durable root is refused.

NOT coupled to XP_ROLE. Nothing ever sets XP_ROLE=lead — absence is how the lead is
identified in stop_gate.py, close.py and session_start.py alike — so a fix that read
absence as unknown would stop the lead repointing at all, which is the only writer
after a mid-session plugin reload (that fires no SessionStart). Durability is the
property; the role is not.
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
    data = Path(tmp) / "data"
    # a plugin copy where a spawned story's worktree carries one: real, and about
    # to be deleted by `close.py story <id> land`
    doomed = data / "worktrees" / "story-000"
    shutil.copytree(DURABLE, doomed / "plugins" / "xp-plugin")
    repo = Path(tmp) / "repo"
    (repo / ".xp").mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    (data / "env.json").write_text(
        json.dumps({"plugin_root": str(DURABLE), "plugin_version": "0.0.0"}) + "\n"
    )
    env = {k: v for k, v in os.environ.items() if k != "XP_ROLE"}
    env |= {"XP_DATA": str(data), "HOME": tmp}
    hook = doomed / "plugins" / "xp-plugin" / "scripts" / "stop_gate.py"
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
if str(doomed) not in recorded:
    sys.exit(0)
print(f"the pin was moved to a root close deletes: {recorded}", file=sys.stderr)
sys.exit(1)
