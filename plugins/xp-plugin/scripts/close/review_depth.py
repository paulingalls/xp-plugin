"""Render the effective story-review depth from the card and reviewed draft."""

import re

from env import data_root

DEPTH = re.compile(r"^Close review:\s*(standard|deep)\b", re.M)
STORY = re.compile(r"^####\s+(\S+)\s", re.M)
RANK = {"standard": 0, "deep": 1}


def _declared(text: str) -> str | None:
    match = DEPTH.search(text)
    return match.group(1) if match else None


def render(card: str) -> str:
    card_depth = _declared(card)
    story = STORY.search(card)
    if not story:
        return (
            f"Close review: {card_depth} — effective depth. The story card assigns this depth."
            if card_depth
            else ""
        )
    draft = data_root() / "plans" / f"{story.group(1)}.plan.md"
    try:
        draft_depth = _declared(draft.read_text())
    except FileNotFoundError:
        draft_depth = None
    except (OSError, UnicodeDecodeError):
        return (
            "Close review: deep — effective depth. The plan review's depth was unreadable, so the"
            " review fails safe to deep."
        )
    if not card_depth and not draft_depth:
        return ""
    if card_depth == "deep" and draft_depth == "standard":
        return (
            "Close review: deep — effective depth. The story card assigns deep;"
            " plan review recorded standard and cannot lower it."
        )
    if draft_depth:
        effective = max((depth for depth in (card_depth, draft_depth) if depth), key=RANK.get)
        return f"Close review: {effective} — effective depth. Plan review assigned {draft_depth}."
    return f"Close review: {card_depth} — effective depth. The story card assigns this depth."
