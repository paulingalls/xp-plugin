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

# config.yml holds the tier land runs; constraints.md is the rubric the reviewer
# applied; system.md's worktree lifecycle lines are shell-executed by spawn/close.
# Editing any of them after a review changes the gate, not the tree.
GATE_FILES = (".xp/config.yml", ".xp/constraints.md", ".xp/system.md")


def land_refusal(state: dict, key: str, base: str) -> str:
    """Whether the recorded round describes the tree in front of us — the whole
    question every land leg asks, in ONE implementation. `key` is the leg's own
    spelling of its review command, which is all that legitimately differs."""
    rerun = f"Run `close.py {key} review`"
    if state.get("review_base") != base:
        return (
            f"refused: the recorded round did not cover this tree — it was based on"
            f" {str(state.get('review_base'))[:8]}, today's merge base is {base[:8]}."
            f" {rerun}"
        )
    shown = state.get("shown_sha", git("rev-parse", "HEAD").stdout.strip())
    if git("merge-base", "--is-ancestor", shown, "HEAD", check=False).returncode:
        return (
            f"refused: HEAD does not contain {shown[:8]}, the tree you were shown —"
            " the reviewer's commits are not in what would merge, so the recorded"
            f" round describes no tree. {rerun}"
        )
    if blocking := state["rounds"][-1]["blocking"]:
        return (
            "refused: the last review round left blocking findings:\n  "
            + "\n  ".join(blocking)
            + "\nFix them (or review again once fixed) — a flag cannot clear these"
        )
    if hit := sorted(f for f in _files(f"{shown}..HEAD") if f in GATE_FILES):
        return (
            f"refused: {', '.join(hit)} changed since the round recorded at"
            f" {shown[:8]} — a gate file is what land RUNS, so no later check"
            f" re-reads it. {rerun}"
        )
    return ""


def merge_source(trunk: str, merge_mode: str) -> str:
    """The ref land integrates, fetched and fully qualified — every message repeats
    it verbatim, so an ambiguous name would send the lead to merge the wrong ref."""
    if merge_mode == "pr" and origin_trunk_sha(trunk):
        return f"refs/remotes/origin/{trunk}"
    return f"refs/heads/{trunk}"


def _files(rng: str) -> set[str]:
    return set(git("diff", "--no-renames", "--name-only", rng).stdout.splitlines())


def unmerged(ref: str) -> bool:
    return git("merge-base", "--is-ancestor", ref, "HEAD", check=False).returncode != 0


def overlapping(ref: str, base: str) -> list[str]:
    """Anchored at the merge base, not at the trunk tip recorded before the review:
    review no longer refuses while trunk is ahead of the fork point, so a
    since-the-review window would be inert for exactly that case."""
    return sorted(_files(f"{base}..{ref}") & _files(f"{base}..HEAD"))


def collision(ref: str, files: list[str]) -> str:
    """It NAMES the files: the practice it defends (DESIGN §11) is a human one
    nothing else watches."""
    return (
        f"refused: {ref} changed files this story also changed, and no review covered"
        " the two together:\n  " + "\n  ".join(files) + "\n"
        f"Run `git merge {ref}` here and review again — but first ask whether two"
        " stories are sharing a file domain, because that is what this refusal sees"
    )


def run_checks(verify: str, tier: str, where: str = "") -> str:
    if not tier:
        # SAYS SO rather than refusing: hook-lib.sh's run_tier refuses an unset
        # tier, and the two legs disagreeing is worth a card (f6c00b18) — but the
        # defect worth fixing now is the SILENCE. A merge gated by Verify alone is
        # legal; one the lead believes a tier gated is not.
        print("no tests.<tier> in .xp/config.yml — Verify alone gates this", file=sys.stderr)
    for label, cmd in (("Verify", verify), ("test tier", tier)):
        if cmd and subprocess.run(cmd, shell=True).returncode != 0:
            return f"refused: {label} red{where}: {cmd}"
    return ""


def gates(ref: str, verify: str, tier_key: str, pending: bool) -> str:
    """Verify and the tier, run on the tree that will EXIST. Merging INTO the story
    branch rather than in the tree holding trunk: same merged content either way,
    and this arm needs no second worktree and strands no foreign tree mid-merge.

    The tier COMMAND is read from the staged tree too, never before it: one
    arriving on trunk otherwise gates the tree it replaced."""
    from work import config_block_value

    if not pending:
        return run_checks(verify, config_block_value("tests", tier_key))
    staged = git("merge", "--no-commit", "--no-ff", ref, check=False)
    try:
        if staged.returncode != 0:
            return (
                f"refused: merging {ref} here conflicts. Resolve it on this branch,"
                " review the post-resolution diff, then land"
            )
        return run_checks(
            verify, config_block_value("tests", tier_key), f" on the tree merged with {ref}"
        )
    finally:
        git("merge", "--abort", check=False)
