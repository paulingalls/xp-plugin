#!/usr/bin/env python3
"""Stop hook, advisory: block once on a red Verify; nudge on a stale digest.

Deterministic reads only (constraint 7); honors stop_hook_active with no
block-count assumptions; degrades to silence on anything unexpected.
"""

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from work import data_root


def git(*args: str) -> str:
    r = subprocess.run(["git", *args], capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else ""


def digest_is_stale() -> bool:
    path = data_root() / "session.md"
    if not path.exists():
        return False
    first = path.read_text(errors="replace").splitlines()[0]
    if " at " not in first:
        return True  # stampless never reads fresh (session_start convention)
    stamp = first.rsplit(" at ", 1)[1].strip()
    distance = git("rev-list", "--count", f"{stamp}..HEAD")
    return distance != "0" if distance else True


def has_in_progress_story() -> bool:
    plan = Path(".xp/plan.md")
    if not plan.exists():
        return False
    return any(
        ln.startswith("#### ") and "[in-progress]" in ln
        for ln in plan.read_text(errors="replace").splitlines()
    )


def main() -> int:
    data = json.load(sys.stdin)
    if data.get("stop_hook_active"):
        return 0
    session = str(data.get("session_id", "unknown"))[:64]
    status_path = data_root() / "markers" / f"{session}.test-status"
    if status_path.exists():
        status = json.loads(status_path.read_text())
        if status.get("red"):
            print(
                json.dumps(
                    {
                        "decision": "block",
                        "reason": (
                            f"story Verify last ran red: {status.get('verify')}"
                            " — fix it or explicitly defer with a work.md record"
                        ),
                    }
                )
            )
            return 0
    if has_in_progress_story() and digest_is_stale():
        print(
            json.dumps(
                {
                    "systemMessage": (
                        "session digest is stale — one-line next-step update"
                        " before stopping (you are its sole writer)"
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
