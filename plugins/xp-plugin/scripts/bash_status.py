#!/usr/bin/env python3
"""Bash-outcome telemetry for the Stop gate — the one sanctioned exception (DESIGN §4).

Payload shapes are from LIVE captures, not docs: a failing Bash command fires
PostToolUseFailure with a top-level `error: "Exit code N\\n..."` and no
tool_response; a PostToolUse(Bash) event itself implies success (its
tool_response has no exit_code). Registered under BOTH events.

Matching: the command must contain a shell segment that STARTS WITH an
in-progress story's config-known Verify string — a mention (commit message,
grep) is not an invocation. One marker per verify (constraint 10: story B's
green must not hide story A's red).
"""

import hashlib
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from close import story_card, verify_commands
from work import data_root


def in_progress_verifies() -> list[str]:
    plan_path = Path(".xp/plan.md")
    if not plan_path.exists():
        return []
    plan = plan_path.read_text(errors="replace")
    verifies = []
    for ln in plan.splitlines():
        if ln.startswith("#### ") and "[in-progress]" in ln:
            story_id = ln.removeprefix("#### ").split(" ", 1)[0]
            card, _ = story_card(plan, story_id)
            if v := verify_commands(card):
                verifies.append(v)
    return verifies


def invoked_verify(command: str) -> str | None:
    """The verify a command actually RUNS: a segment startswith, never a substring."""
    segments = [s.strip() for s in re.split(r"&&|\|\||[;|]", command)]
    for verify in in_progress_verifies():
        if any(seg.startswith(verify) for seg in segments):
            return verify
    return None


def marker_file(session: str, verify: str) -> Path:
    d = data_root() / "markers"
    d.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha1(verify.encode()).hexdigest()[:8]
    return d / f"{session}.{digest}.test-status"


def main() -> int:
    data = json.load(sys.stdin)
    command = str(data.get("tool_input", {}).get("command", ""))
    verify = invoked_verify(command)
    if verify is None:
        return 0
    event = data.get("hook_event_name", "")
    if event == "PostToolUseFailure":
        if not str(data.get("error", "")).startswith("Exit code "):
            return 0  # permission denial / interruption — not a test outcome
        red = True
    elif event == "PostToolUse":
        red = False  # the event itself implies the command succeeded
    else:
        return 0
    session = str(data.get("session_id", "unknown"))[:64]
    marker_file(session, verify).write_text(json.dumps({"verify": verify, "red": red}))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (Exception, SystemExit):
        sys.exit(0)
