"""Validate and label takeover of a handed-back story worktree."""

import argparse
import fcntl
import subprocess
from pathlib import Path

from handoff import handoff_state, marker_path


def parse(argv: list[str]):
    parser = argparse.ArgumentParser(
        prog="spawn.py resume",
        description="launch a fresh teammate in a handed-back story worktree",
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
        if tree.is_dir():
            return f"refused: {story_id} is RUNNING in {tree} — wait for its handback"
        return f"refused: {story_id} was NEVER SPAWNED — use `spawn.py {story_id}` first"
    state = handoff_state(root, story_id)
    if state is None:
        return (
            f"refused: {marker} is unreadable, so it cannot prove the teammate stopped —"
            " read `work.py list`, repair the handoff, then resume"
        )
    kind = state.get("state")
    if kind not in ("STOPPED", "FINISHED"):
        return f"refused: {marker} has invalid handoff state {kind!r} — repair it before resuming"
    if not tree.is_dir():
        return f"refused: {kind} worktree {tree} is missing — recover it before resuming"
    actual = subprocess.run(
        ["git", "branch", "--show-current"], cwd=tree, capture_output=True, text=True
    )
    if actual.returncode or actual.stdout.strip() != branch:
        return (
            f"refused: {tree} is not on {kind.lower()} branch {branch} — restore that checkout"
            " before resuming"
        )
    if kind == "FINISHED":
        status = subprocess.run(
            ["git", "status", "--porcelain"], cwd=tree, capture_output=True, text=True
        )
        if status.returncode or status.stdout.strip():
            dirt = status.stdout.strip() or status.stderr.strip() or "git status failed"
            return f"refused: FINISHED handback {tree} became dirty:\n{dirt}"
    return ""


def inherited_evidence(tree: Path, trunk: str) -> str:
    def read(*args: str) -> str:
        done = subprocess.run(["git", *args], cwd=tree, capture_output=True, text=True)
        return done.stdout.strip() if done.returncode == 0 else "(unreadable)"

    return (
        "### Inherited from the predecessor — NOT yours\n\n"
        f"Commits already on this branch:\n\n```text\n{read('log', '--oneline', f'{trunk}..HEAD')}"
        f"\n```\n\nUncommitted paths:\n\n```text\n{read('status', '--porcelain')}\n```\n\n"
        "Read `git log -p` and `git diff` as predecessor EVIDENCE, never as your own work:"
        " your handback names only what you commit from here. If you adopt an uncommitted"
        " path, verify it and say so; do not claim a red you did not observe. Commit every"
        " path you adopt or hand the rest back.\n"
    )
