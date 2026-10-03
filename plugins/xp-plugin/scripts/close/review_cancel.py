"""Handle a stopped review without recording coverage."""

from review_card import card_now


def card_changed(story_id: str, card: str):
    """A plan read mid-write can cut this card short and look edited, so a cancel
    needs the same differing card on two consecutive polls."""
    seen = [""]

    def changed() -> bool:
        now = card_now(story_id)
        agreed = bool(now) and now != card and now == seen[0]
        seen[0] = now
        return agreed

    return changed
