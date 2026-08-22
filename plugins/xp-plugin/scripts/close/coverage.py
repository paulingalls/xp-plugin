"""What a recorded review covers, and what only executing the merge can tell you.

Trunk moving is not evidence the review went stale — only files BOTH diffs touch
can interact somewhere no later review makes cheap to find. So motion buys a trial
merge and overlap buys a round: something EXECUTED the merge result is a different
property from someone REVIEWED it.
"""

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from close import git, origin_trunk_sha


def merge_source(trunk: str, merge_mode: str) -> str:
    """The ref land integrates, fetched and fully qualified — every message repeats
    it verbatim, so an ambiguous name would send the lead to merge the wrong ref."""
    if merge_mode == "pr" and origin_trunk_sha(trunk):
        return f"refs/remotes/origin/{trunk}"
    return f"refs/heads/{trunk}"


def _files(rng: str) -> set[str]:
    return set(git("diff", "--name-only", rng).stdout.splitlines())


def unmerged(ref: str) -> bool:
    return git("merge-base", "--is-ancestor", ref, "HEAD", check=False).returncode != 0


def overlapping(ref: str, base: str) -> list[str]:
    """Anchored at the merge base, not at the trunk tip recorded before the review:
    review no longer refuses while trunk is ahead of the fork point, so a
    since-the-review window would be inert for exactly that case."""
    return sorted(_files(f"{base}..{ref}") & _files(f"{base}..HEAD"))


def collision(ref: str, files: list[str]) -> str:
    """DESIGN §11's cross-story collision check, which was never built — so it NAMES
    the files: the practice it defends is a human one nothing else watches."""
    return (
        f"refused: {ref} changed files this story also changed, and no review covered"
        " the two together:\n  " + "\n  ".join(files) + "\n"
        f"Run `git merge {ref}` here and review again — but first ask whether two"
        " stories are sharing a file domain, because that is what this refusal sees"
    )


def run_checks(verify: str, tier: str, where: str = "") -> str:
    for label, cmd in (("Verify", verify), ("test tier", tier)):
        if cmd and subprocess.run(cmd, shell=True).returncode != 0:
            return f"refused: story {label} red{where}: {cmd}"
    return ""


def gates(ref: str, verify: str, tier: str, pending: bool) -> str:
    """Verify and the tier, run on the tree that will EXIST. Merging INTO the story
    branch rather than in the tree holding trunk: same merged content either way,
    and this arm needs no second worktree and strands no foreign tree mid-merge."""
    if not pending:
        return run_checks(verify, tier)
    staged = git("merge", "--no-commit", "--no-ff", ref, check=False)
    try:
        if staged.returncode != 0:
            return (
                f"refused: merging {ref} here conflicts. Resolve it on this branch,"
                " review the post-resolution diff, then land"
            )
        return run_checks(verify, tier, f" on the tree merged with {ref}")
    finally:
        git("merge", "--abort", check=False)
