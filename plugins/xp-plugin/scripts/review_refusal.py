"""Refusals preserve work and return correction authority to the lead."""

from review_report import NO_ROUND


def abort_text(reviewed_head: str, why: str, recorded: str = NO_ROUND, salvage=False) -> str:
    return f"refused: {why}\n{recorded} Work and artifacts remain; the lead owns correction."
