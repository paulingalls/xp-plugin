"""Read the card used to bind a review."""


def card_now(story_id: str) -> str:
    from close import story_card
    from work import plan_path

    try:
        return story_card(plan_path().read_text(), story_id)[0]
    except (KeyError, OSError, UnicodeError):
        return ""
