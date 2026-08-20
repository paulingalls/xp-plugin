#!/usr/bin/env python3
"""Post-merge bookkeeping for close.py: gate-state cleanup, the close log,
and story-branch deletion.

Extracted at story-008 round 4: close.py had reached 496 lines against the
500 hard cap (constraints #8), and these three are cohesive and independent
of cmd_land's control flow — they take a story and a branch, not a pipeline.
"""

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from work import card_title, data_root


def git(*args: str, check: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], capture_output=True, text=True, check=check)


def delete_story_markers(story_id: str) -> None:
    """Clear the story's test-status markers rather than writing a green into
    them: those files are session-scoped gate state, and a green close.py never
    measured is close.py forging another session's measurement (DESIGN §4,
    constraints #6). The [done] flip is what honestly releases the Stop gate;
    this only stops dead files accumulating."""
    for path in (data_root() / "markers").glob(f"*.{story_id}.test-status"):
        path.unlink(missing_ok=True)


def render_merge_body(rounds: list[dict]) -> str:
    """Every round, labelled by its TRUE round number.

    Index IS the round: a round is recorded only with a valid report, so there are
    no gaps to renumber over. story-008 appended only when a VERDICT line parsed,
    labelled by list position, and its own merge body reads "Review round 1" for
    round 6.
    """
    out = []
    for i, r in enumerate(rounds, 1):
        counts = " · ".join(f"{len(r[k])} {k}" for k in ("fixed", "blocking", "noted"))
        out.append(f"Review round {i}: {counts}")
        out += [f"  {k}: {item}" for k in ("fixed", "blocking", "noted") for item in r[k]]
    return "\n".join(out)


def log_close(story_id: str, card: str, rounds: list[dict], merge_sha: str) -> None:
    """APPEND one line per close. A single overwritten file would be the
    project-global mutable marker constraints #10 calls a design error; a log is
    not, it survives two closes in one sprint, and the retro gets the history."""
    from datetime import datetime, timezone

    record = {
        "story": story_id,
        "title": card_title(card),
        "rounds": rounds,
        "merge_sha": merge_sha,
        "closed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    with (data_root() / "closes.jsonl").open("a") as fh:
        fh.write(json.dumps(record) + "\n")


def delete_story_branch(branch: str) -> list[str]:
    """Delete the story branch, LOCAL FIRST.

    Local first so `-d`'s merged check runs while the upstream ref still exists.
    Belt-and-braces at both call sites, where the merge is already reachable —
    the measurement behind the ordering (story-007) was taken from the story
    branch before the merge, where it IS load-bearing.

    Idempotent on both sides: `gh pr merge --delete-branch` may already have
    removed either, and reporting an already-done step as outstanding prints a
    remediation that fails on re-run — a wolf-cry on the only channel M1's
    "no hand-steps" has. The remote is asked with ls-remote rather than a
    tracking ref, because `git fetch` without --prune leaves stale ones.

    Returns the commands that failed, for the caller to surface.
    """
    local_exists = git("rev-parse", "--verify", "-q", f"refs/heads/{branch}").returncode == 0
    if local_exists and git("branch", "-d", branch).returncode != 0:
        return [f"git branch -d {branch}"]
    on_origin = git("ls-remote", "--exit-code", "--heads", "origin", branch).returncode == 0
    if on_origin and git("push", "origin", "--delete", branch).returncode != 0:
        return [f"git push origin --delete {branch}"]
    return []
