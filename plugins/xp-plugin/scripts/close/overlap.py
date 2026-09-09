"""What review covers and what merge execution proves."""

import shlex
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from close import git, origin_trunk_sha

# config.yml holds the tier land runs; constraints.md is the rubric the reviewer
# applied; system.md's worktree lifecycle lines are shell-executed by spawn/close.
# Editing any of them after a review changes the gate, not the tree.
GATE_FILES = (".xp/config.yml", ".xp/constraints.md", ".xp/system.md")
_NO_RECEIPT = object()
MISSING_RECEIPT = object()
_RECEIPT_KEYS = {"tier", "command", "tree", "head", "verdict", "ran_by", "reused"}


def unresolved_blocking(state: dict) -> list:
    """Blocking findings nothing has cleared.

    List position stopped answering this when salvage began inserting an older
    attempt at its chronological place. A salvaged round is an attempt recorded
    OUT OF ORDER: it never saw the rounds already recorded, and they never saw
    it. So it clears nothing, and nothing already recorded clears it. What does
    clear it is a round LAUNCHED after it was queued, whose bundle carried its
    findings — and `round_file` is that order: every launch takes the next free
    round number, and rotation pushes an unrecorded attempt above it. A salvage
    carrying no round_file cannot be placed, so it stays unresolved; refusing is
    loud and a lead can review again, landing over a finding is neither.
    """
    rounds = state.get("rounds") or []
    live = [r for r in rounds if not r.get("salvaged")]
    current = live[-1] if live else {}
    latest = current.get("round_file") or 0
    return list(current.get("blocking") or []) + [
        f
        for r in rounds
        if r.get("salvaged") and (r.get("round_file") or latest + 1) > latest
        for f in r.get("blocking") or []
    ]


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
    if blocking := unresolved_blocking(state):
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
    """Compare from the fork point; a since-review window misses trunk motion."""
    return sorted(_files(f"{base}..{ref}") & _files(f"{base}..HEAD"))


def collision(ref: str, files: list[str]) -> str:
    listed = "\n  ".join(files)
    return (
        f"refused: {ref} overlaps files no review covered together:\n  {listed}\n"
        "Merge it here and review again — gate files and trunk releases have no later reader"
    )


def report_merge(story_id: str, files: list[str]) -> None:
    print(f"{story_id} shares these with the branch it merged into:")
    print("  " + "\n  ".join(files))


def run_one(label: str, cmd: str | list[str], where: str = "") -> str:
    shown = cmd if isinstance(cmd, str) else shlex.join(cmd)
    try:
        rc = subprocess.run(cmd, shell=isinstance(cmd, str)).returncode
    except OSError:
        rc = 127
    if rc == 127:
        return (
            f"refused: {label} could not be RUN{where}: {shown}\nNothing was measured"
            " — it is not on PATH where this ran, which is a harness or sandbox"
            " problem, not a red tree. Fix where it runs"
        )
    return f"refused: {label} red{where}: {shown}" if rc else ""


def tier_refusal(tier: str | None, tier_key: str) -> str:
    """The ONE answer every leg gives a tier that cannot run — hook-lib.sh's
    run_tier says these words at the commit leg. None = no tier applies here."""
    if tier not in ("", "EDIT-ME"):
        return ""
    return (
        f"refused: tests.{tier_key} is unset or still EDIT-ME in .xp/config.yml — no test"
        f" tier ran. Set tests.{tier_key} to your suite's command, then retry"
    )


def run_checks(
    verify: list[list[str]], tier: str | None, where: str = "", tier_key: str = "story"
) -> str:
    if refusal := tier_refusal(tier, tier_key):
        return refusal
    for label, commands in (("Verify", verify), ("test tier", [tier] if tier else [])):
        for cmd in commands:
            if red := run_one(label, cmd, where):
                return red
    return ""


def _receipt_matches(receipt: object, tier: str, tree: str) -> tuple[bool, str]:
    if receipt is MISSING_RECEIPT:
        return False, "missing"
    valid = (
        isinstance(receipt, dict)
        and set(receipt) == _RECEIPT_KEYS
        and receipt.get("tier") == "full"
        and all(
            isinstance(receipt.get(key), str) and receipt[key]
            for key in ("command", "tree", "head")
        )
        and receipt.get("verdict") == "passed"
        and receipt.get("ran_by") in ("start", "land")
        and isinstance(receipt.get("reused"), bool)
    )
    if not valid:
        return False, "unreadable"
    if receipt["tree"] != tree:
        return False, "tree changed"
    if receipt["command"] != tier:
        return False, "command changed"
    return True, "reused"


def gates(
    ref: str,
    verify: list[list[str]],
    tier_key: str,
    pending: bool,
    prior_receipt: object = _NO_RECEIPT,
) -> tuple[str, dict | None]:
    """Verify and the tier, run on the tree that will EXIST. Merging INTO the story
    branch rather than in the tree holding trunk: same merged content either way,
    and this arm needs no second worktree and strands no foreign tree mid-merge.

    The tier COMMAND is read from the staged tree too, never before it: one
    arriving on trunk otherwise gates the tree it replaced."""
    from work import config_block_value

    staged = None
    if pending:
        staged = git("merge", "--no-commit", "--no-ff", ref, check=False)
    try:
        if staged is not None and staged.returncode != 0:
            return (
                f"refused: merging {ref} here conflicts. Resolve it on this branch,"
                " review the post-resolution diff, then land",
                None,
            )
        where = f" on the tree merged with {ref}" if pending else ""
        tier = config_block_value("tests", tier_key)
        if refusal := tier_refusal(tier, tier_key):
            return refusal, None
        if prior_receipt is _NO_RECEIPT:
            return run_checks(verify, tier, where, tier_key), None
        written = git("write-tree", check=False)
        if written.returncode:
            return (
                f"refused: Git could not write tree for the full tier: {written.stderr.strip()}",
                None,
            )
        tree = written.stdout.strip()
        reusable, decision = _receipt_matches(prior_receipt, tier, tree)
        if reusable:
            print("full tier receipt reused")
            return "", dict(prior_receipt, reused=True)
        print(f"full tier receipt {decision}; running the shipping tree")
        if red := run_checks(verify, tier, where, tier_key):
            return red, None
        return "", {
            "tier": "full",
            "command": tier,
            "tree": tree,
            "head": git("rev-parse", "HEAD").stdout.strip(),
            "verdict": "passed",
            "ran_by": "land",
            "reused": False,
        }
    finally:
        if staged is not None:
            git("merge", "--abort", check=False)
