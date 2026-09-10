"""Parse the paths a story card declares for review scope."""

import re

DECORATION = re.compile(r"(?:(?<!/)\(new\)|\s+\([^()]*\))\s*$")
TOP_LEVEL_COMMA = re.compile(r",(?![^()]*\))")


def _bare(entry: str) -> str:
    """Git prints neither Markdown ticks nor a trailing card annotation.

    Run twice because either decoration may sit inside the other (issue #45).
    """
    for _ in range(2):
        entry = DECORATION.sub("", entry.strip().strip("`"))
    return entry.strip()


def file_entries(text: str) -> list[str]:
    declared = []
    for raw in TOP_LEVEL_COMMA.split(text):
        if not (raw := raw.strip()):
            continue
        path = _bare(raw)
        balanced = all(path.count(o) == path.count(c) for o, c in ("()", "[]", "{}"))
        if not (balanced and re.fullmatch(r"[^\s]+", path)):
            raise ValueError(
                f"the Files entry {raw!r} is not a plausible path; use bare"
                " comma-separated paths, end the block at the next `Label:` line,"
                " and keep rationale in the card body"
            )
        if path not in declared:
            declared.append(path)
    return declared


def declared_files(card: str) -> set[str]:
    declared, in_files = set(), False
    for line in card.splitlines():
        if line.startswith("Files:"):
            in_files, line = True, line.removeprefix("Files:")
        elif in_files and re.match(r"[A-Za-z][A-Za-z ]*:", line):
            in_files = False
        if in_files:
            declared.update(file_entries(line))
    return declared
