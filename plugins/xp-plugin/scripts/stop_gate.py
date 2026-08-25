#!/usr/bin/env python3
"""Stop hook, advisory: block once on any red Verify still in play.

Deterministic reads only; honors stop_hook_active; fail-silent. The stale-digest
nudge was removed: Stop fires every turn (not at session end), so it nagged the
user constantly, and its message could never reach the lead anyway — staleness
is handled once, correctly, at SessionStart.
"""

import json
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from bash_status import in_progress_stories
from work import chdir_repo_root, data_root


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


def main() -> int:
    if sys.stdin.isatty():
        print(f"{Path(__file__).name} is a hook; invoke it with a JSON payload on stdin.")
        return 0
    data = json.load(sys.stdin)
    if not chdir_repo_root():
        return 0
    if data.get("stop_hook_active"):
        return 0
    session = str(data.get("session_id", "unknown"))[:64]
    if red := red_verify_in_play(session):
        print(
            json.dumps(
                {
                    "decision": "block",
                    "reason": (
                        f"story Verify last ran red: {red} — fix it, or mark its story"
                        " done/deferred in the plan if the red is accepted"
                    ),
                }
            )
        )
        return 0
    return 0


if __name__ == "__main__":
    try:
        rc = main()
    except Exception:  # advisory: never break a session — but never in silence,
        traceback.print_exc(file=sys.stderr)  # or a dead hook reads as a passing one
        rc = 0
    sys.exit(rc)
