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
from close import fail, story_card
from work import (
    card_digest,
    card_lines,
    chdir_repo_root,
    edit_plan,
    flip_status,
    plan_path,
    ready_marker_path,
    stale_plan,
)


def drift(story_id: str, card: str) -> str:
    """ "" when this card is the one the plan reviewer saw; otherwise the refusal.

    The reviewed TEXT is stored beside its digest so the refusal can show what
    moved. A digest alone can only assert that something did, and the lead is one
    diff away from knowing whether to re-review or to undo.
    """
    marker = ready_marker_path(story_id)
    if not marker.exists():
        return (
            f"refused: {story_id} reads [ready] but nothing minted it — the bracket was"
            " typed, not earned. After the plan review, clear the card with"
            f" `spawn.py ready {story_id}`, which records the card the reviewer saw."
        )
    minted = json.loads(marker.read_text())
    if minted["digest"] == card_digest(card):
        return ""
    diff = difflib.unified_diff(
        card_lines(minted["card"]),
        card_lines(card),
        "reviewed",
        "now",
        lineterm="",
        n=1,
    )
    return (
        f"refused: {story_id} was edited after its plan review — spawning would launch"
        " a teammate on text no reviewer saw:\n"
        + "\n".join(diff)
        + f"\nRe-review the card, put its heading back to [planned], and re-run"
        f" `spawn.py ready {story_id}`."
    )


def mint(story_id: str) -> int:
    """The one leg that clears a card, so the [ready] flip and the digest cannot
    come apart: a lead who types the bracket mints nothing and spawn refuses."""
    if not plan_path().exists():
        return fail(
            "refused: "
            + (stale_plan() or f"no plan at {plan_path()} — is this an xp-managed repo?")
        )
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
    digest = card_digest(card)
    marker = ready_marker_path(story_id)
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(json.dumps({"digest": digest, "card": card}, ensure_ascii=False))
    edit_plan(lambda text: flip_status(text, story_id, "planned", "ready"))
    print(f"{story_id} [planned] -> [ready], digest {digest} — edit the card and spawn refuses")
    return 0


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="spawn.py ready", description=mint.__doc__)
    p.add_argument("story_id")
    story_id = p.parse_args(argv).story_id
    if not chdir_repo_root():
        return fail("refused: not inside a git repository")
    return mint(story_id)
