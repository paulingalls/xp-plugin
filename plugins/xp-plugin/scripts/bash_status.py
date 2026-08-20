#!/usr/bin/env python3
"""PostToolUse(Bash) hook: record Verify outcomes for the Stop gate.

The ONE sanctioned telemetry exception (DESIGN §4): a session-scoped scratch
marker, never a work record. Matching is against the in-progress stories'
config-known Verify strings — no heuristic test-command detection (the
six-spellings evasion class). No derivable signal -> no marker (advisory).
"""

import json
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


def main() -> int:
    data = json.load(sys.stdin)
    command = str(data.get("tool_input", {}).get("command", ""))
    response = data.get("tool_response", {})
    exit_code = response.get("exit_code") if isinstance(response, dict) else None
    if exit_code is None:
        return 0
    matched = next((v for v in in_progress_verifies() if v in command), None)
    if matched is None:
        return 0
    session = str(data.get("session_id", "unknown"))[:64]
    markers = data_root() / "markers"
    markers.mkdir(parents=True, exist_ok=True)
    (markers / f"{session}.test-status").write_text(
        json.dumps({"verify": matched, "red": exit_code != 0})
    )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (Exception, SystemExit):
        sys.exit(0)
