#!/usr/bin/env python3
"""Stop hook, advisory: block once on any red Verify still in play.

Deterministic state updates only; honors stop_hook_active; fail-silent. The stale-digest
nudge was removed: Stop fires every turn (not at session end), so it nagged the
user constantly. Plugin environment drift is instead repaired silently here.
"""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from bash_status import in_progress_stories
from env import env_path, plugin_version, run_hook, write_env
from work import chdir_repo_root, data_root

PLUGIN_ROOT = Path(__file__).parent.parent


def repoint_env() -> bool:
    if os.environ.get("XP_ROLE", "lead") != "lead":
        return False
    try:
        running_version = plugin_version(PLUGIN_ROOT)
        if running_version == "unknown":
            return False
        try:
            recorded = json.loads(env_path().read_text())
        except FileNotFoundError:
            recorded = {}
        if not isinstance(recorded, dict):
            raise ValueError("env.json must contain an object")
        if (
            recorded.get("plugin_root") == str(PLUGIN_ROOT)
            and recorded.get("plugin_version") == running_version
        ):
            return False
        write_env(PLUGIN_ROOT, running_version)
    except Exception:
        return False
    return True


def red_verify_in_play(session: str) -> str | None:
    """A red marker whose verify still belongs to an in-progress story.

    A story flipped to done/deferred in plan.md releases its red honestly —
    that IS the deferral path the block message names.
    """
    live = {story_id for story_id, _verify in in_progress_stories()}
    for path in (data_root() / "markers").glob(f"{session}.*.test-status"):
        try:
            status = json.loads(path.read_text())
        except Exception:
            continue  # one corrupt file must not disable the gate
        if status.get("red") and status.get("story") in live:
            return str(status.get("verify"))  # the verify is what the lead can act on
    return None


def main(data: dict) -> int:
    if not chdir_repo_root():
        return 0
    if data.get("stop_hook_active"):
        return 0
    repoint_env()
    session = str(data.get("session_id", "unknown"))[:64]
    if red := red_verify_in_play(session):
        reason = (
            f"story Verify last ran red: {red} — fix it, or mark its story"
            " done/deferred in the plan if the red is accepted"
        )
        print(json.dumps({"decision": "block", "reason": reason}))
    return 0


if __name__ == "__main__":
    run_hook(main)
