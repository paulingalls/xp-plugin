#!/usr/bin/env python3
"""Bash-outcome telemetry for the Stop gate — the one sanctioned exception (DESIGN §4).

Payload shapes are from LIVE captures, not docs. Claude routes a failing Bash
command to PostToolUseFailure (`error: "Exit code N\\n..."`), so a PostToolUse
carrying its {stdout,stderr,...} dict PROVES success. Codex 0.147.0 fires
PostToolUse for failures too and no field of that payload carries the outcome —
so green is written only where it is PROVEN, never inferred from an event.

Matching: the command must contain a shell segment that STARTS WITH an
in-progress story's config-known Verify string — a mention (commit message,
grep) is not an invocation. One marker per STORY, not per verify string
(markers are always story-scoped): two stories can carry byte-identical Verify commands — sprint-1
shipped a pair — and a verify-keyed marker cannot tell whose status it holds.
"""

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from close import story_card, verify_commands
from env import run_hook
from work import chdir_repo_root, data_root, plan_path


def in_progress_stories() -> list[tuple[str, str]]:
    """(story_id, verify) for every [in-progress] story that declares a Verify."""
    if not (path := plan_path()).exists():
        return []
    plan = path.read_text(errors="replace")
    stories = []
    for ln in plan.splitlines():
        if ln.startswith("#### ") and "[in-progress]" in ln:
            story_id = ln.removeprefix("#### ").split(" ", 1)[0]
            card, _ = story_card(plan, story_id)
            if v := verify_commands(story_id, card, False)[0]:
                stories.append((story_id, v))
    return stories


def invoked_stories(command: str, event_is_green: bool) -> list[tuple[str, str]]:
    """Every story whose Verify the command's OVERALL exit actually entails.

    A list, not one story: byte-identical Verify commands genuinely entail both
    stories' status, and each gets its own marker.

    Segments must EQUAL the verify exactly (a subset like `verify::test_one` or a
    mention is not the verify). Green additionally requires every separator to the
    verify's right to be `&&` — the tool's shell has no pipefail, so `verify | tail`,
    `verify; echo`, `verify || true` all exit 0 over a red verify (proven live).
    Red accepts any position: a conservative false-red self-clears on the next
    honest green run. Anything else -> no marker (advisory fail-open).
    """
    tokens = [t.strip() for t in re.split(r"(&&|\|\||[;|]|\n)", command)]
    hits = []
    for story_id, verify in in_progress_stories():
        for i, tok in enumerate(tokens):
            if tok == verify:
                rest_seps = [t for t in tokens[i + 1 :] if t in ("&&", "||", ";", "|", "")]
                if not event_is_green or all(t == "&&" for t in rest_seps):
                    hits.append((story_id, verify))
                    break
    return hits


def marker_file(session: str, story_id: str) -> Path:
    d = data_root() / "markers"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{session}.{story_id}.test-status"


def main(data: dict) -> int:
    if not chdir_repo_root():
        return 0
    command = str(data.get("tool_input", {}).get("command", ""))
    event = data.get("hook_event_name", "")
    if event == "PostToolUseFailure":
        if not str(data.get("error", "")).startswith("Exit code "):
            return 0  # permission denial / interruption — not a test outcome
        red = True
    elif event == "PostToolUse":
        if not isinstance(data.get("tool_response"), dict):
            return 0
        red = False  # the command succeeded; entailment for the verify checked below
    else:
        return 0
    hits = invoked_stories(command, event_is_green=not red)
    if not hits:
        return 0
    session = str(data.get("session_id", "unknown"))[:64]
    for story_id, verify in hits:
        marker_file(session, story_id).write_text(
            json.dumps({"story": story_id, "verify": verify, "red": red})
        )
    return 0


if __name__ == "__main__":
    run_hook(main)
