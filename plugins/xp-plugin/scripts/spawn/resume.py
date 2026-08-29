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


def handback_recovery(tree: Path, story_id: str) -> str:
    return (
        f" Recover by reviewing and committing the remaining work in {tree},"
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
    state = handoff_state(root, story_id)
    if state is None:
        return (
            f"refused: {marker} is unreadable, so it cannot prove the teammate stopped —"
            " read `work.py list`, repair the handoff, then resume"
        )
    # A locked RUNNING marker proves a dead launch; FINISHED would forge clean success.
    kind = state.get("state") if marker.exists() else "NEVER SPAWNED"
    if kind == "NEVER SPAWNED" and not tree.is_dir():
        return f"refused: {story_id} was NEVER SPAWNED — use `spawn.py {story_id}` first"
    if kind not in ("STOPPED", "FINISHED", "RUNNING", "NEVER SPAWNED"):
        recovery = "discard/re-spawn or record a real STOPPED recovery; never forge FINISHED"
        return f"refused: invalid handoff state {kind!r} in {marker} — {recovery}"
    if not tree.is_dir():
        return f"refused: {kind} worktree {tree} is missing — recover it before resuming"
    if kind in ("RUNNING", "NEVER SPAWNED"):
        return (
            f"refused: {story_id} left {tree} with no handback and nothing holds its launch"
            f' lock — an INTERRUPTED spawn, not a RUNNING teammate. Write "STOPPED" into'
            f" {marker} to take that tree over, or remove the worktree and re-spawn"
        )
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
        if status.returncode:
            return f"refused: FINISHED handback {tree} is unmeasurable: {status.stderr.strip()}"
        if dirt := status.stdout.strip():
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
