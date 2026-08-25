"""What the teammate handed back: the tree's state, and whether it is a story.

Extracted from spawn.py when the codex-posture patch took that file to 503 of the
500-line cap — over-cap means extract, not scroll (constraint 8). These two are
one thing: the second is the only caller of the first that judges, and both
measure the worktree AS HANDED OVER rather than as it stands.
"""

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from bookkeep import worktree_command
from work import plan_path


def tree_state(tree: Path) -> tuple[str, str]:
    """(HEAD, porcelain) — the guard's baseline. Raises rather than passing
    stdout through: a FAILED git returns empty output, which reads as an empty
    porcelain and a HEAD unequal to the flip's — clean and committed, the one
    wrong answer the guard can give."""

    def out(*args: str) -> str:
        r = subprocess.run(["git", *args], cwd=tree, capture_output=True, text=True)
        if r.returncode != 0:
            raise OSError(f"git {args[0]} failed in {tree}: {(r.stderr or r.stdout).strip()}")
        return r.stdout.strip()

    return out("rev-parse", "HEAD"), out("status", "--porcelain")


def unclean_teammate_result(
    tree: Path, handed_over: tuple[str, str], story_id: str, resumed: bool = False
) -> str:
    """ "" when the teammate left a clean, committed story behind; otherwise the
    refusal, naming both recoveries.

    Both halves measure against the tree AS HANDED OVER: raw porcelain would charge
    the teammate with whatever the bootstrap command dirtied before it started.
    """
    flip_head, handed_dirty = handed_over
    system = tree / ".xp/system.md"
    try:
        text = system.read_text() if system.exists() else ""
        teardown, problem = worktree_command(text, "teardown")
    except UnicodeDecodeError as exc:
        teardown, problem = "", f"Could not read {system}: {exc}"
    discard = f"`git worktree remove {tree}`"
    if teardown:
        discard = (
            f"running {teardown!r} and then `git worktree remove {tree}`"
            " (add --force if teardown leaves files behind)"
        )
    recovery = (
        f" Recover by `spawn.py resume {story_id}`, which takes this tree and its commits"
        f" over with a fresh teammate; by committing by hand in {tree}; or by {discard},"
        f" putting {story_id}'s heading back to [ready] in {plan_path()}, and re-spawning."
        + (f" {problem}." if problem else "")
    )
    if resumed:
        import resume

        recovery = resume.handback_recovery(tree, story_id)
    try:
        head, dirty = tree_state(tree)
    except OSError as e:
        return f"refused: the story is unverified — {e}.{recovery}"
    if left := sorted(set(dirty.splitlines()) - set(handed_dirty.splitlines())):
        return "refused: the teammate left work uncommitted in {}:\n{}\n{}".format(
            tree, "\n".join(left), recovery
        )
    if resumed and dirty:
        return "refused: inherited takeover work remains uncommitted in {}:\n{}\n{}".format(
            tree, dirty, recovery
        )
    if head == flip_head:
        return f"refused: the teammate made no commits of its own in {tree}.{recovery}"
    return ""
