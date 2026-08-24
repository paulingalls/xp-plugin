#!/usr/bin/env python3
"""Post-merge bookkeeping and rendering for close.py.

Everything here takes a story and a branch, never a pipeline — that is the
seam, and it is why these live outside cmd_land's control flow.
"""

import json
import os
import re
import signal
import subprocess
import sys
from contextlib import suppress
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from work import card_title, data_root

# templates/config.yml ships this number commented out, and test_dogfood pins the two
# together: a default a project reads in prose and never gets is worse than no default.
TEARDOWN_TIMEOUT = 60


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


def render_sprint_prior(rounds: list[dict]) -> str:
    """The MODE SWITCH (note bae0b87b): findings handed in bound the pass to
    validating them, none means re-derive everything. Sprint-002 had neither."""
    body = render_merge_body(rounds)
    if not body:
        return "none — run the full pass yourself"
    return body + "\n\nvalidate that each was addressed; do not re-derive the diff."


def render_land_preview(
    verify: str, tier: str, merge_mode: str, branch: str, trunk: str, pr_steps: tuple, pending: bool
) -> str:
    """What land WOULD do. A preview that drifts from the real steps certifies a
    plan nobody runs, so both arms read the command lists cmd_land executes.
    """
    out = [f"would run: {verify}"] + ([f"would run: {tier}"] if tier else [])
    if pending:
        out.append(f"...on a trial merge with {trunk} — staged, then aborted either way")
    if merge_mode == "pr":
        pr_cmds, pr_sync, pr_bookkeep = pr_steps
        out += [" ".join(c) for c in pr_cmds + pr_sync]
        out.append("(flip the plan to [done])")
        out += [" ".join(c) for c in [*pr_bookkeep, ["git", "branch", "-d", branch]]]
    else:
        out.append(f"git merge --no-ff {branch} on {trunk}")
        out.append("(flip the plan to [done])")
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
    """Delete the story branch, REMOTE FIRST: `-d` compares against the upstream ref
    when one exists, so the reviewer's commits — never pushed to the story branch —
    make it refuse a branch already merged to HEAD. With the remote gone it falls
    back to the HEAD check and still refuses a genuinely unmerged one. ls-remote,
    not a tracking ref: `git fetch` without --prune leaves stale ones.
    """
    on_origin = git("ls-remote", "--exit-code", "--heads", "origin", branch).returncode == 0
    if on_origin and git("push", "origin", "--delete", branch).returncode != 0:
        return [f"git push origin --delete {branch}"]
    local_exists = git("rev-parse", "--verify", "-q", f"refs/heads/{branch}").returncode == 0
    if local_exists and git("branch", "-d", branch).returncode != 0:
        return [f"git branch -d {branch}"]
    return []


def held_trunk_tree(trunk: str) -> tuple[str, str]:
    """(path of ANOTHER worktree holding <trunk>, error). Cheap and structural, so
    cmd_land asks BEFORE Verify rather than after ~2 min of tier."""
    path = ""
    for ln in git("worktree", "list", "--porcelain").stdout.splitlines():
        if ln.startswith("worktree "):
            path = ln[9:]
        elif ln == f"branch refs/heads/{trunk}":
            if Path(path).resolve() == Path.cwd().resolve():
                return "", ""
            if git("-C", path, "status", "--porcelain").stdout.strip():
                return "", (
                    f"refused: {trunk} is checked out at {path}, which is dirty —"
                    " the merge lands there, so clean it first"
                )
            return path, ""
    return "", ""


def worktree_command(system_md: str, action: str) -> tuple[str, str]:
    """(command, problem) — at most one is ever non-empty, for `worktree <action>`.

    ONE backticked command or nothing runs: a substring match would execute the
    path in "none needed - see [a backticked path]". Deterministic, no judging
    prose (#7). Unreadable and absent stay DIFFERENT things here and the callers
    decide what that costs — bootstrap refuses the spawn, teardown reports and
    continues — because reading it wrong is the one failure this parser can hide.
    """
    wanted = f"worktree {action}"
    for ln in system_md.splitlines():
        label, sep, value = ln.partition(":")
        if not sep or label.strip().strip("*-# ").casefold() != wanted:
            continue
        value = value.strip().rstrip(".")
        if m := re.fullmatch(r"`([^`]+)`", value):
            return m.group(1), ""
        if "`" not in value and re.match(r"none\b", value, re.I):
            return "", ""
        return "", (
            f"cannot read the Worktree {action} line in .xp/system.md: {ln.strip()!r}"
            " — the value must be ONE backticked command, or start with 'none'"
        )
    return "", ""


def bootstrap_command(system_md: str) -> tuple[str, str]:
    return worktree_command(system_md, "bootstrap")


def _teardown(tree: str, timeout_value: str) -> str:
    """Run the project's teardown inside the doomed checkout — "" or what went wrong."""
    system = Path(tree, ".xp/system.md")
    command, problem = worktree_command(system.read_text() if system.exists() else "", "teardown")
    if not command:
        return problem
    timeout = TEARDOWN_TIMEOUT
    if timeout_value:
        if timeout_value.isdigit() and int(timeout_value) > 0:
            timeout = int(timeout_value)
        else:
            print(
                f"teardown_timeout: {timeout_value!r} is not a positive integer — used {timeout}s",
                file=sys.stderr,
            )
    # Its own session, so the timeout kill reaches the whole process group: a
    # compound command leaves a shell whose children outlive a kill of the shell.
    proc = subprocess.Popen(command, shell=True, cwd=tree, start_new_session=True)
    try:
        if proc.wait(timeout=timeout):
            return f"Worktree teardown failed ({command!r})"
    except subprocess.TimeoutExpired:
        with suppress(ProcessLookupError):
            os.killpg(proc.pid, signal.SIGKILL)
        proc.wait()
        return f"Worktree teardown timed out after {timeout}s ({command!r})"
    return ""


def remove_story_worktree(tree: str, timeout_value: str = "") -> list[str]:
    """The teardown, then the removal that happens either way.

    Only `git branch -d` needs the worktree gone — MEASURED, the merge succeeds
    while the branch is checked out elsewhere. So it runs just before the delete:
    every refusal above names a next action the lead takes in that tree.

    The merge has LANDED by here, so a teardown reports and never refuses — and a
    raise refuses hardest of all, taking the removal and the bookkeeping below it
    down with a half-closed story (measured: a .xp/system.md that is not UTF-8).
    """
    try:
        issue = _teardown(tree, timeout_value)
    except Exception as e:
        issue = f"Worktree teardown could not run: {e!r}"
    removed = git("worktree", "remove", "--force", tree).returncode == 0
    failed = [f"git worktree remove --force {tree}"] if not removed else []
    if issue:
        suffix = " — worktree removed; inspect external state manually" if removed else ""
        failed.insert(0, issue + suffix)
    return failed
