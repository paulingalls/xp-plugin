#!/usr/bin/env python3
"""Post-merge bookkeeping and rendering for close.py.

Everything here takes a story and a branch, never a pipeline — that is the
seam, and it is why these live outside cmd_land's control flow.
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
    """Clear the story's test-status markers rather than writing a green into them:
    a green close.py never measured is a forged measurement (constraints #6). The
    [done] flip releases the Stop gate; this only stops dead files accumulating."""
    for path in (data_root() / "markers").glob(f"*.{story_id}.test-status"):
        path.unlink(missing_ok=True)


def render_merge_body(rounds: list[dict]) -> str:
    """Every round, labelled by its TRUE round number.

    Index IS the round: a round is recorded only with a valid report, so there
    are no gaps to renumber over.
    """
    out = []
    for i, r in enumerate(rounds, 1):
        counts = " · ".join(f"{len(r[k])} {k}" for k in ("fixed", "blocking", "noted"))
        out.append(f"Review round {i}: {counts}")
        out += [f"  {k}: {item}" for k in ("fixed", "blocking", "noted") for item in r[k]]
    return "\n".join(out)


def render_prior_rounds(rounds: list[dict]) -> str:
    """Earlier rounds, for the next round's bundle — "" before round 2.

    A fixing reviewer with no memory re-edits the last round's fixes and reverses
    what it deliberately punted.
    """
    body = render_merge_body(rounds)
    if not body:
        return ""
    return body + (
        "\n\nDo NOT re-litigate a settled fix. DO verify each `fixed` item still"
        " holds in the tree you were given."
    )


def render_land_preview(
    verify: str, tier: str, merge_mode: str, branch: str, trunk: str, pr_steps: tuple
) -> str:
    """What land WOULD do. A preview that drifts from the real steps certifies a
    plan nobody runs, so both arms read the command lists cmd_land executes.
    """
    out = [f"would run: {verify}"] + ([f"would run: {tier}"] if tier else [])
    if merge_mode == "pr":
        pr_cmds, pr_sync, pr_bookkeep = pr_steps
        out += [" ".join(c) for c in pr_cmds + pr_sync]
        out.append("(flip .xp/plan.md to [done])")
        out += [" ".join(c) for c in [*pr_bookkeep, ["git", "branch", "-d", branch]]]
    else:
        out.append(f"git merge --no-ff {branch} on {trunk}")
        out.append("(flip .xp/plan.md to [done], then git commit --amend --no-edit)")
        steps = [["git", "branch", "-d", branch]]
        if git("remote").stdout.strip():  # both pushes are runtime-guarded on a remote
            steps = [
                ["git", "push", "origin", trunk],
                *steps,
                ["git", "push", "origin", "--delete", branch],
            ]
        out += [" ".join(c) for c in steps]
    return "".join(f"{ln}\n" for ln in out)


def render_noted(rounds: list[dict]) -> str:
    """The reviewer's deliberate punts, for the lead to file per PROCESS.md.

    EVERY round's: an item punted in round 1 and never filed is still owed.
    """
    noted = [n for r in rounds for n in r["noted"]]
    if not noted:
        return ""
    return "noted by the reviewer, not fixed — file these per PROCESS.md:\n" + "".join(
        f"  {n}\n" for n in noted
    )


def log_close(story_id: str, card: str, rounds: list[dict], merge_sha: str) -> None:
    """APPEND one line per close. An overwritten file would be the project-global
    mutable marker constraints #10 forbids; a log survives two closes in one
    sprint and the retro gets the history."""
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
    """Delete the story branch, LOCAL FIRST — so `-d`'s merged check still has the
    upstream ref to check against.

    Idempotent both sides: `gh pr merge --delete-branch` may have removed either,
    and reporting a done step as outstanding prints a remediation that fails on
    re-run. ls-remote, not a tracking ref: `git fetch` without --prune leaves
    stale ones.
    """
    local_exists = git("rev-parse", "--verify", "-q", f"refs/heads/{branch}").returncode == 0
    if local_exists and git("branch", "-d", branch).returncode != 0:
        return [f"git branch -d {branch}"]
    on_origin = git("ls-remote", "--exit-code", "--heads", "origin", branch).returncode == 0
    if on_origin and git("push", "origin", "--delete", branch).returncode != 0:
        return [f"git push origin --delete {branch}"]
    return []
