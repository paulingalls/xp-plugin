"""Render the effective story-review depth from the card and reviewed draft."""

import re

from env import data_root

DEPTH = re.compile(r"^Close review:\s*(standard|deep)\b", re.M)
STORY = re.compile(r"^####\s+(\S+)\s", re.M)


def _declared(text: str) -> str | None:
    match = DEPTH.search(text)
    return match.group(1) if match else None


def render(card: str) -> str:
    from ready import credential
    from work import ready_marker_path

    card_depth = _declared(card)
    story = STORY.search(card)
    minted = credential(ready_marker_path(story.group(1))) if story else None
    floor_cards = [minted.get("minted_card", minted["card"])] if minted else []
    if minted:
        floor_cards += [change["card"] for change in minted.get("amendments", [])]
        floor_cards += [record["before"] for record in minted.get("review_acceptances", [])]
    floor = "deep" if any(_declared(text) == "deep" for text in floor_cards) else None
    draft = data_root() / "plans" / f"{story.group(1)}.plan.md" if story else None
    try:
        draft_depth = _declared(draft.read_text()) if draft else None
    except FileNotFoundError:
        draft_depth = None
    except (OSError, UnicodeDecodeError):
        return (
            "Close review: deep — effective depth. The plan review's depth was unreadable, so the"
            " review fails safe to deep."
        )
    if floor == "deep" and card_depth != "deep":
        return (
            "Close review: deep — effective depth. A prior credentialed card assigns deep"
            " and remains the floor."
        )
    if card_depth == "deep" and draft_depth == "standard":
        return (
            "Close review: deep — effective depth. The story card assigns deep;"
            " plan review recorded standard and cannot lower it."
        )
    if draft_depth:
        return f"Close review: {draft_depth} — effective depth. Plan review assigned {draft_depth}."
    if card_depth:
        return f"Close review: {card_depth} — effective depth. The story card assigns this depth."
    return ""
