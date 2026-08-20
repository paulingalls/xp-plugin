#!/usr/bin/env python3
"""Spawn the story-reviewer and capture its verdict — close.py's review leg.

Extracted from close.py at story-008 rather than left inline: story-011 lands
`free` mode in close.py this same sprint, and 442 + ~75 breaches the 500-line
hard cap (constraints.md #8). This block is the only seam — everything else in
close.py is preflight, merge and bookkeeping.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

PLUGIN_ROOT = Path(__file__).parent.parent

# A verdict rides into SessionStart's recovery block, and session_start.py
# truncates the TAIL of its output — so an unbounded verdict silently evicts
# constraints.md from the next lead's profile. Bounded at the write.
VERDICT_CAP = 200

# The reviewer runs under --dangerously-skip-permissions (spawn.claude_argv) in
# the LEAD'S LIVE TREE. story-007 accepted that unboundedness because a teammate
# sits in a throwaway worktree; that justification does not transfer here, and
# the charter's "do not edit code" is advisory-by-declaration (constraints #5).
# MEASURED at story-007 close: --disallowedTools DOES bound under bypass,
# --allowedTools does not. Bash stays, so the charter's scratch runs still work.
REVIEWER_DENY = ["--disallowedTools", "Edit,Write,NotebookEdit"]


def charter() -> str:
    """agents/story-reviewer.md, frontmatter stripped.

    The reviewer runs as a top-level headless session, not as a subagent, so the
    harness never loads the agent file — inlining it is the mechanism and the
    path is the fallback (spawn.py's rule).
    """
    text = (PLUGIN_ROOT / "agents" / "story-reviewer.md").read_text()
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) == 3:
            return parts[2].strip()
    return text.strip()


def extract_verdict(result: str) -> str:
    """The LAST VERDICT line, capped. Empty when the reviewer emitted none."""
    for line in reversed(result.splitlines()):
        candidate = line.strip()
        if candidate.startswith("VERDICT"):
            if len(candidate) > VERDICT_CAP:
                return candidate[: VERDICT_CAP - 1] + "…"
            return candidate
    return ""


def run(prompt: str, cwd: Path, dry_run: bool = False) -> tuple[str, str]:
    """Launch the reviewer. Returns (result_text, error) — never raises on a
    reviewer that crashes, prints prose, or is missing from PATH.

    Imports are function-local: spawn.py imports from close.py and close.py
    imports this module, so module-level edges would close a cycle.
    """
    from spawn import claude_argv, resolve_role, run_agent

    _harness, model, effort = resolve_role("reviewer")
    argv = claude_argv(model, effort, "json") + REVIEWER_DENY
    if dry_run:
        print("would launch: " + " ".join(argv))
        print(prompt)
        return "", ""
    # capture + --output-format json means total silence for the whole run;
    # without this line a multi-minute review is indistinguishable from a hang.
    print(f"spawning story-reviewer ({model}) — no output until it finishes", file=sys.stderr)
    try:
        proc = run_agent(argv, cwd, prompt, role="reviewer", capture=True)
    except OSError as e:  # claude absent from PATH
        return "", f"could not launch the reviewer: {e}"
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()[:500]
        return "", f"reviewer exited {proc.returncode}: {detail}"
    try:
        return json.loads(proc.stdout)["result"], ""
    except (ValueError, KeyError, TypeError):
        return "", f"reviewer output was not the expected JSON: {proc.stdout.strip()[:300]}"
