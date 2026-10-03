"""Validate and label takeover of a handed-back story worktree."""

import argparse
import fcntl
import subprocess
import sys
from pathlib import Path

from close import leg
from handoff import RESULTS, STAGES, handoff_state, marker_path


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
    noun = leg(story_id)[0]
    return (
        f" Recover by reviewing and committing any remaining work in {tree}. If the"
        f" committed work completes the card, run `close.py {noun} review` from {tree};"
        f" if work remains, run `spawn.py resume {story_id}`. Do not remove the inherited"
        " tree."
    )


_OWNED = {}


def owns(handle, root, story_id):
    return not handle.closed and _OWNED.get(handle) == (root.resolve(), story_id)


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
    _OWNED[handle] = (root.resolve(), story_id)
    return handle, ""


def validate(root: Path, story_id: str, tree: Path, branch: str) -> str:
    marker = marker_path(root, story_id)
    state = handoff_state(root, story_id)
    if state is None:
        return (
            f"refused: execution stage selection is unknown because {marker} is unreadable —"
            " restore its saved bytes from preserved evidence, then resume; work and logs remain"
        )
    # A locked RUNNING marker proves a dead launch; FINISHED would forge clean success.
    kind = state.get("state") if marker.exists() else "NEVER SPAWNED"
    if kind == "NEVER SPAWNED" and tree.is_dir():
        return (
            f"refused: missing executor checkpoint beside {tree}; preserve artifacts "
            f"and restore the handoff before resuming"
        )
    if kind == "NEVER SPAWNED" and not tree.is_dir():
        return f"refused: {story_id} was NEVER SPAWNED — use `spawn.py {story_id}` first"
    if kind not in ("STOPPED", "FINISHED", "RUNNING", "NEVER SPAWNED"):
        recovery = "discard/re-spawn or record a real STOPPED recovery; never forge FINISHED"
        return f"refused: invalid handoff state {kind!r} in {marker} — {recovery}"
    stages = state.get("stages", {})
    if not isinstance(stages, dict) or any(
        name not in STAGES or result not in RESULTS for name, result in stages.items()
    ):
        return f"refused: invalid stage state in {marker} — restore {RESULTS} stage values"
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
    import contextlib

    from completion import validate as checkpoint

    try:
        with contextlib.chdir(tree):
            checkpoint(story_id, state)
    except ValueError as error:
        return f"refused: {error}"
    if kind == "FINISHED":
        status = subprocess.run(
            ["git", "status", "--porcelain"], cwd=tree, capture_output=True, text=True
        )
        if status.returncode:
            return f"refused: FINISHED handback {tree} is unmeasurable: {status.stderr.strip()}"
        if dirt := status.stdout.strip():
            print(
                f"FINISHED completion invalidated by dirty takeover work in {tree}:\n{dirt}",
                file=sys.stderr,
            )
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


def validation_only(root, story_id, held):
    import contextlib

    import close
    import spawn
    from handoff import mark_handoff
    from work import plan_path

    prior = handoff_state(root, story_id) or {}
    sequence = prior.get("checkpoint", {}).get("review_sequence")
    if not sequence or sequence["status"] == "completed":
        return None
    card, _ = close.story_card(plan_path().read_text(), story_id)
    tree = spawn.worktree_path(story_id)
    if error := validate(root, story_id, tree, spawn.story_branch(card, story_id)):
        return close.fail(error)
    with contextlib.chdir(tree):
        rc = close.cmd_review(story_id, held=held, explicit=False)
        if not rc:
            from completion import inputs, record

            record(story_id, "reviewer", "ran", inputs(story_id, card))
    if not rc:
        mark_handoff(root, story_id, True, "retained review; interrupted validation completed")
    return rc
