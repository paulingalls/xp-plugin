"""Card text: the header a card carries, the lines its credential hashes,
and the status flip that rewrites one bracket.

Pure text, no I/O and no plan path: extracted from work.py when the
sprint-021 back-merge of v0.21.4 and v0.21.5 pushed that file past this
project's hard line cap. Neither side was over alone.
"""

import hashlib


def card_title(card: str) -> str:
    """The story title from a card header, or "" when it carries no em-dash."""
    header = card.splitlines()[0]
    return header.split("— ", 1)[1].split(" [")[0].strip() if "— " in header else ""


def card_lines(card: str) -> list[str]:
    """The card lines that its credential hashes and drift refusal diffs."""
    lines = [ln.rstrip() for ln in card.splitlines()]
    head = lines[0]
    if head.endswith("]"):
        lines[0] = head[: head.rindex("[")].rstrip()
    while lines and not lines[-1]:
        lines.pop()
    return lines


def card_digest(card: str) -> str:
    return hashlib.sha256("\n".join(card_lines(card)).encode()).hexdigest()[:16]


def flip_status(text: str, heading: str, frm: str, to: str) -> str:
    exact = heading.startswith("## ")  # a milestone heading is whole; a card's is a prefix
    out = []
    for ln in text.splitlines(keepends=True):
        head, sep, tail = ln.rstrip().rpartition(f"[{frm}]")
        if sep and not tail and (head == heading if exact else ln.startswith(heading)):
            ln = f"{head}[{to}]" + ln[len(ln.rstrip()) :]
        out.append(ln)
    return "".join(out)
