#!/usr/bin/env python3
"""Spawn the story-reviewer and read its structured report — close.py's review leg.

Extracted from close.py at story-008 rather than left inline: this block is the
only seam, and close.py runs against the 500-line hard cap (constraints.md #8).
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

PLUGIN_ROOT = Path(__file__).parent.parent

REPORT_KEYS = ("fixed", "blocking", "noted")
# The report rides into the merge body, closes.jsonl and SessionStart's recovery
# block. Bounded AT THE WRITE, not at each read: the predecessor's json bounded
# size by validating on the way in, and three unbounded lists in the section that
# already evicted constraints.md is the same defect with more shapes.
ITEM_CAP = 400
LIST_CAP = 20

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
    from spawn import _read_shipped

    text = _read_shipped(PLUGIN_ROOT / "agents" / "story-reviewer.md")
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) == 3:
            return parts[2].strip()
    return text.strip()


def report_path(story_id: str, round_n: int) -> Path:
    """Where this round's report goes. ROUND-scoped, not story-scoped: the round
    index advances only on a RECORDED round, so every failed attempt at round N
    reuses N's path and a leftover from a crashed reviewer would certify a round
    that produced nothing. The caller unlinks before launching."""
    from work import data_root

    d = data_root() / "reports"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{story_id}.round-{round_n}.json"


def _cap(items: list) -> list:
    kept = [i if len(i) <= ITEM_CAP else i[: ITEM_CAP - 1] + "…" for i in items[:LIST_CAP]]
    if len(items) > LIST_CAP:
        kept[-1] = (
            f"(+{len(items) - LIST_CAP + 1} more, see {' / '.join(REPORT_KEYS)} in the report)"
        )
    return kept


def read_report(path: Path) -> tuple[dict, str]:
    """(report, error). Replaces the VERDICT-line grep, which was forgeable by
    design (story-002) and then defeated by backticks (story-008). This fixes
    PARSING, not forgery — a reviewer under bypass writes any path it likes.
    """
    if not path.exists():
        return {}, (
            f"the reviewer wrote no report at {path} — its findings are above and"
            " are all that survives. No report, no round"
        )
    try:
        data = json.loads(path.read_text())
    except ValueError as e:
        return {}, f"the reviewer's report is not JSON ({e})"
    if not isinstance(data, dict):
        return {}, "the reviewer's report is not JSON — expected an object"
    missing = [k for k in REPORT_KEYS if not isinstance(data.get(k), list)]
    if missing:
        return {}, f"the reviewer's report is missing list keys: {', '.join(missing)}"
    return {k: _cap([str(i) for i in data[k]]) for k in REPORT_KEYS}, ""


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
