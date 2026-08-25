"""Validate and label takeover of a stopped story's existing worktree."""

import argparse
import fcntl
import json
import subprocess
from pathlib import Path

from handoff import marker_path


def parse(argv: list[str]):
    parser = argparse.ArgumentParser(
        prog="spawn.py resume",
        description="launch a fresh teammate in a stopped story's existing worktree",
    )
    parser.add_argument("story_id")
    parser.add_argument("executor", nargs="?", default="")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args(argv)


def remint_route(story_id: str) -> str:
    return (
        "Put the heading back to [planned], run `plan_review.py"
        f" {story_id} <plan-draft>`, then `spawn.py ready {story_id}` and"
        f" `spawn.py resume {story_id}`."
    )


def handback_recovery(tree: Path, story_id: str) -> str:
    return (
        f" Recover by reviewing and committing the remaining predecessor diff in {tree},"
        f" then run `spawn.py resume {story_id}`; do not remove the inherited tree."
    )


def acquire(root: Path, story_id: str):
    path = root / "locks" / f"{story_id}.resume.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+")
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        handle.close()
        return None, (
            f"refused: {story_id} already has a teammate launch in progress — wait for"
            " that handback"
        )
    return handle, ""


def validate(root: Path, story_id: str, tree: Path, branch: str) -> str:
    marker = marker_path(root, story_id)
    if not marker.exists():
        return (
            f"refused: {story_id} has no stopped-teammate handoff — its teammate may still"
            f" be running in {tree}; wait for its handback before resuming"
        )
    try:
        state = json.loads(marker.read_text())
    except (OSError, ValueError):
        state = None
    if not isinstance(state, dict):
        return (
            f"refused: {marker} is unreadable, so it cannot prove the teammate stopped —"
            " read `work.py list`, repair the handoff, then resume"
        )
    if not tree.is_dir():
        return f"refused: stopped worktree {tree} is missing — recover it before resuming"
    expected = subprocess.run(
        ["git", "show-ref", "--verify", "--quiet", f"refs/heads/{branch}"], cwd=tree
    )
    if expected.returncode:
        return f"refused: stopped branch {branch} is missing — recover it before resuming"
    actual = subprocess.run(
        ["git", "branch", "--show-current"], cwd=tree, capture_output=True, text=True
    )
    if actual.returncode or actual.stdout.strip() != branch:
        return (
            f"refused: {tree} is not on stopped branch {branch} — restore that checkout"
            " before resuming"
        )
    return ""


def dirty_handover(tree: Path) -> str:
    result = subprocess.run(
        ["git", "status", "--porcelain"], cwd=tree, capture_output=True, text=True, check=True
    )
    dirty = result.stdout.strip()
    if not dirty:
        return ""
    return (
        "### Inherited working-tree evidence\n\n"
        "These paths were dirty before this fresh run and belong to the predecessor:\n\n"
        f"```text\n{dirty}\n```\n\n"
        "Inspect `git diff` as predecessor evidence. If you adopt it, verify and attribute"
        " it explicitly; do not claim a red you did not observe. Commit every adopted path"
        " or hand the remaining diff back.\n"
    )
