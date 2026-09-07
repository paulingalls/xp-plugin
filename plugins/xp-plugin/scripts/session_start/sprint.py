import re


def sprint_sections(text: str) -> tuple[str, list[str]]:
    at = [
        (match[1], section.strip())
        for section in re.split(r"(?=^### )", text, flags=re.M)
        if (match := re.match(r"### Sprint (\d+)\b", section))
    ]
    # int() orders; the id keeps the PLAN'S spelling, the only one a slate matches
    current = max((raw for raw, _section in at), key=int, default="")
    return current, [section for raw, section in at if raw == current]
