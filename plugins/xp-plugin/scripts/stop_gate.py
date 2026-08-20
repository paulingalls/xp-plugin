#!/usr/bin/env python3
"""Stop hook, advisory: block once on any red Verify still in play; nudge on a
stale digest. Deterministic reads only; honors stop_hook_active; fail-silent.
"""

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from bash_status import in_progress_verifies
from work import chdir_repo_root, data_root


def git(*args: str) -> str:
    r = subprocess.run(["git", *args], capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else ""


def digest_is_stale() -> bool:
    path = data_root() / "session.md"
    if not path.exists():
        return False
    first = (path.read_text(errors="replace").splitlines() or [""])[0]
    if " at " not in first:
        return True  # stampless never reads fresh (session_start convention)
    stamp = first.rsplit(" at ", 1)[1].strip()
    distance = git("rev-list", "--count", f"{stamp}..HEAD")
    return distance != "0" if distance else True


def red_verify_in_play(session: str) -> str | None:
    """A red marker whose verify still belongs to an in-progress story.

    A story flipped to done/deferred in plan.md releases its red honestly —
    that IS the deferral path the block message names.
    """
    live = set(in_progress_verifies())
    for path in (data_root() / "markers").glob(f"{session}.*.test-status"):
        try:
            status = json.loads(path.read_text())
        except Exception:
            continue  # one corrupt file must not disable the gate
        if status.get("red") and status.get("verify") in live:
            return str(status.get("verify"))
    return None


def main() -> int:
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
                        " done/deferred in .xp/plan.md if the red is accepted"
                    ),
                }
            )
        )
        return 0
    if in_progress_verifies() and digest_is_stale():
        print(
            json.dumps(
                {
                    "systemMessage": (
                        "xp: the session digest is stale — have the lead write its"
                        " one-line next-step update before you quit"
                    )
                }
            )
        )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (Exception, SystemExit):
        sys.exit(0)
