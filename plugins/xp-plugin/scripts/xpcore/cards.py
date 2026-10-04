"""plan.md cards: `#### <id> — <title>   [<status>]` headings and the lines under them."""

import fcntl
import os
import re
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from xpcore.config import data_root, refuse

STATUSES = ("planned", "in-progress", "done", "retired")
HEADING = re.compile(r"#### (\S+) — (.*?)\s+\[([\w-]+)\]\s*")
SECTION = re.compile(r"(#{1,4}) ")


@dataclass
class Card:
    id: str
    title: str
    status: str
    lines: list[str]

    def field(self, name: str) -> str:
        prefix = f"{name}:"
        return next((ln[len(prefix) :].strip() for ln in self.lines if ln.startswith(prefix)), "")

    @property
    def files(self) -> list[str]:
        paths = (p.strip().removesuffix("(new)").strip() for p in self.field("Files").split(","))
        return [p for p in paths if p]

    @property
    def acceptance(self) -> str:
        return self.field("Acceptance")

    @property
    def executor(self) -> str:
        value = self.field("Executor")
        return "" if value in ("", "(default)") else value

    @property
    def text(self) -> str:
        return "\n".join(self.lines) + "\n"


def plan_path() -> Path:
    return data_root() / "plan.md"


def _spans(text: str) -> list[tuple[int, int, Card]]:
    """(first line, end line, card) per heading; a card ends at the next heading of any level."""
    lines = text.splitlines()
    spans: list[tuple[int, int, Card]] = []
    for i, line in enumerate(lines):
        if not SECTION.match(line):
            continue
        if spans and spans[-1][1] == -1:
            start, _, card = spans[-1]
            spans[-1] = (start, i, card)
        if match := HEADING.fullmatch(line):
            spans.append((i, -1, Card(match[1], match[2], match[3], [])))
    if spans and spans[-1][1] == -1:
        spans[-1] = (spans[-1][0], len(lines), spans[-1][2])
    for start, end, card in spans:
        body = lines[start:end]
        while body and not body[-1].strip():
            body.pop()
        card.lines = body
    return spans


def _read_plan() -> str:
    path = plan_path()
    if not path.is_file():
        refuse(f"no plan at {path}; run xp.py setup, or write the slate there")
    return path.read_text()


def read_cards(text: str | None = None) -> list[Card]:
    return [card for _, _, card in _spans(_read_plan() if text is None else text)]


def _locate(text: str, card_id: str) -> tuple[int, int, Card]:
    found = [span for span in _spans(text) if span[2].id == card_id]
    if not found:
        refuse(f"no card {card_id} in {plan_path()}; check the id, or add the card to the plan")
    if len(found) > 1:
        refuse(f"{len(found)} cards are headed {card_id} in {plan_path()}; rename all but one")
    return found[0]


def find_card(card_id: str) -> Card:
    return _locate(_read_plan(), card_id)[2]


@contextmanager
def plan_lock() -> Iterator[None]:
    """The one lock: parallel stories flip and rewrite cards in the same plan.md."""
    path = data_root() / "plan.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def _write_plan(text: str) -> None:
    path = plan_path()
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp.write_text(text)
    tmp.replace(path)


def _splice(card_id: str, replacement: list[str]) -> None:
    text = _read_plan()
    start, end, card = _locate(text, card_id)
    lines = text.splitlines()
    gap = lines[start + len(card.lines) : end]
    lines[start:end] = replacement + gap
    _write_plan("\n".join(lines) + "\n")


def set_status(card_id: str, status: str) -> None:
    if status not in STATUSES:
        refuse(f"status {status!r} is not one of {', '.join(STATUSES)}; pass one of those")
    with plan_lock():
        card = _locate(_read_plan(), card_id)[2]
        heading = f"#### {card.id} — {card.title}   [{status}]"
        _splice(card_id, [heading, *card.lines[1:]])


def replace_card(card_id: str, new_text: str) -> None:
    replacement = new_text.rstrip("\n").splitlines()
    if not replacement or not HEADING.fullmatch(replacement[0]):
        refuse(f"replacement for {card_id} must start with `#### <id> — <title>   [<status>]`")
    with plan_lock():
        _splice(card_id, replacement)


def sprint_slate(sprint_id) -> str:
    """The `## Sprint <id>` section: its heading down to the next heading at its level or above."""
    wanted = str(sprint_id).lstrip("0") or "0"
    lines = _read_plan().splitlines()
    for i, line in enumerate(lines):
        match = re.match(r"(#{2,3}) Sprint 0*(\d+)\b", line)
        if not match or (match[2].lstrip("0") or "0") != wanted:
            continue
        level = len(match[1])
        end = next(
            (
                j
                for j in range(i + 1, len(lines))
                if (h := SECTION.match(lines[j])) and len(h[1]) <= level
            ),
            len(lines),
        )
        return "\n".join(lines[i:end]).rstrip() + "\n"
    refuse(f"no `## Sprint {sprint_id}` section in {plan_path()}; write the slate there first")


def mint_free(card_id: str, heading: str) -> bool:
    """Append `heading` at the end of `## Free`; False when the card already exists."""
    with plan_lock():
        if card_id in {c.id for c in read_cards()}:
            return False
        lines = _read_plan().rstrip("\n").splitlines()
        if "## Free" not in lines:
            lines += ["", "## Free"]
        start = lines.index("## Free")
        end = next(
            (j for j in range(start + 1, len(lines)) if re.match(r"#{1,3} ", lines[j])),
            len(lines),
        )
        while not lines[end - 1].strip():
            end -= 1
        lines[end:end] = ["", heading]
        _write_plan("\n".join(lines) + "\n")
    return True
