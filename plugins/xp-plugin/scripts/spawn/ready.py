"""The plan-review credential: minted once by the lead, checked at every spawn.

[ready] was a bit with a reader and no writer — a card edited after its review
kept it, and spawn launched an unbounded teammate on text no reviewer saw
(measured three times in sprint-003). The digest binds the credential to the card
text; the bracket is display.
"""

import argparse
import difflib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from close import fail, story_card, verify_refusal
from work import (
    card_digest,
    card_lines,
    chdir_repo_root,
    flip_card,
    missing_plan_refusal,
    plan_path,
    ready_marker_path,
)


def drift(story_id: str, card: str, remediation: str = "") -> str:
    """ "" when this card is the one the plan reviewer saw; otherwise the refusal.

    The reviewed TEXT is stored beside its digest so the refusal can show what
    moved. A digest alone can only assert that something did, and the lead is one
    diff away from knowing whether to re-review or to undo.
    """
    marker = ready_marker_path(story_id)
    recovery = remediation or (
        f"Put the heading back to [planned] and run `spawn.py ready {story_id}`, which"
        " records the card the reviewer saw."
    )
    if not marker.exists():
        return (
            f"refused: {story_id}'s card is cleared and nothing minted it — the bracket"
            f" was typed, not earned, or {marker} was deleted. {recovery}"
        )
    try:
        minted = json.loads(marker.read_text())
        reviewed, digest = minted["card"], minted["digest"]
    except (OSError, ValueError, KeyError, TypeError):
        return (
            f"refused: {marker} is unreadable, so nothing vouches for {story_id} — an"
            f" interrupted mint leaves half of it. {recovery}"
        )
    if digest == card_digest(card):
        return ""
    diff = difflib.unified_diff(
        card_lines(reviewed),
        card_lines(card),
        "reviewed",
        "now",
        lineterm="",
        n=1,
    )
    return (
        f"refused: {story_id} was edited after its plan review — spawning would launch"
        " a teammate on text no reviewer saw:\n" + "\n".join(diff) + f"\n{recovery}"
    )


def mint(story_id: str) -> int:
    """The one leg that clears a card, so the [ready] flip and the digest cannot
    come apart: a lead who types the bracket mints nothing and spawn refuses."""
    if not plan_path().exists():
        return fail("refused: " + missing_plan_refusal())
    try:
        card, status = story_card(plan_path().read_text(), story_id)
    except KeyError as e:
        return fail(f"refused: {e.args[0]}")
    if status != "planned":
        return fail(
            f"refused: {story_id} is [{status}], ready mints from [planned]. To re-mint"
            " after editing a cleared card, put its heading back to [planned] and run the"
            " plan review again — the edit is what the next spawn would have refused."
        )
    if refusal := verify_refusal(story_id, card):
        return fail(refusal + " — fix it before the review, not after the story")
    digest = card_digest(card)
    marker = ready_marker_path(story_id)
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(json.dumps({"digest": digest, "card": card}, ensure_ascii=False))
    flip_card(story_id, "planned", "ready")
    print(f"{story_id} [planned] -> [ready], digest {digest} — next run `spawn.py {story_id}`")
    return 0


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="spawn.py ready", description=mint.__doc__)
    p.add_argument("story_id")
    story_id = p.parse_args(argv).story_id
    if not chdir_repo_root():
        return fail("refused: not inside a git repository")
    return mint(story_id)
