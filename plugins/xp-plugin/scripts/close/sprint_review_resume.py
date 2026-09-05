"""Resume a sprint round whose fixer finished before its closer did."""

import json
import subprocess
from pathlib import Path


def closer_round(rounds: list[dict]) -> dict | None:
    if not rounds:
        return None
    round_ = rounds[-1]
    stages = round_.get("stages", [])
    if not round_.get("incomplete") or stages[-1:] != ["fix"]:
        return None
    # A fixer whose patch was REFUSED — a path outside the card's Files, a hunk that
    # will not apply — leaves the tree unmoved while the round still records what it
    # claimed to fix, and a closer resumed over that certifies fixes in no commit.
    # Absent coverage is a pre-provenance round, not an unmoved one; reviewed_head()
    # proves that case from the reviewer commit itself.
    reviewed = round_.get("reviewed_head")
    unmoved = reviewed is not None and reviewed == round_.get("shown_sha")
    return None if unmoved and round_.get("fixed") else round_


def reviewed_head(round_: dict, head: str, patch: Path, git, reviewer_name: str) -> tuple[str, str]:
    shown = round_.get("shown_sha", "")
    reviewed = round_.get("reviewed_head", "")
    if not reviewed:
        parent = git("rev-parse", f"{head}^", check=False).stdout.strip()
        author = git("show", "-s", "--format=%an", head).stdout.strip()
        saved = patch.read_text() if patch.is_file() else ""
        actual = git("diff", f"{parent}..{head}").stdout

        def patch_id(text: str) -> list[str]:
            return subprocess.run(
                ["git", "patch-id", "--stable"],
                input=text,
                capture_output=True,
                text=True,
            ).stdout.split()

        saved_id = patch_id(saved)[:1]
        exact = bool(saved_id) and saved_id == patch_id(actual)[:1]
        if author != reviewer_name or not parent or not exact:
            return "", (
                "the incomplete round predates resume provenance and its fixer commit"
                " cannot be derived from the saved patch"
            )
        reviewed, shown = parent, head
    if shown != head:
        return "", f"HEAD moved since the incomplete round stopped at {shown[:8]}"
    return reviewed, ""


def keep_incomplete(marker: Path, state: dict, error: str) -> None:
    state["rounds"][-1]["incomplete"] = error
    marker.write_text(json.dumps(state))


def complete(marker: Path, state: dict, round_: dict, reviewed: str, shown: str) -> None:
    coverage = {"reviewed_head": reviewed, "shown_sha": shown}
    state["rounds"][-1] = round_ | coverage
    state.update(coverage)
    marker.write_text(json.dumps(state))
