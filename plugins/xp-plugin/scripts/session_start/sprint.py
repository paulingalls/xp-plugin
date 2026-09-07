import contextlib
import io
import re

from env import sprint_branch


class SprintSelectionError(RuntimeError):
    pass


def _recorded_branch() -> str:
    refusal = io.StringIO()
    try:
        with contextlib.redirect_stderr(refusal):
            return sprint_branch()
    except SystemExit as exc:
        reason = refusal.getvalue().strip().removeprefix("refused: ")
        raise SprintSelectionError(reason or f"sprint branch record refused ({exc.code})") from exc


def select_sprint(text: str) -> tuple[str, list[str], str]:
    at = [
        (match[1], section.strip())
        for section in re.split(r"(?=^### )", text, flags=re.M)
        if (match := re.match(r"### Sprint (\d+)\b", section))
    ]
    highest = max((raw for raw, _section in at), key=int, default="")
    recorded = _recorded_branch()
    if not recorded:
        provenance = (
            f"sprint selection: no sprint branch recorded; highest-numbered fallback selected "
            f"plan Sprint {highest}"
        )
        return highest, [section for raw, section in at if raw == highest], provenance
    if not (match := re.fullmatch(r"sprint-(\d+)", recorded)):
        raise SprintSelectionError(f"recorded branch {recorded} is not named sprint-N")
    number = int(match[1])
    selected = next((raw for raw, _section in at if int(raw) == number), "")
    if not selected:
        available = ", ".join(f"Sprint {raw}" for raw, _section in at) or "none"
        raise SprintSelectionError(
            f"recorded branch {recorded} has no matching heading in the plan; "
            f"available headings: {available}"
        )
    provenance = f"sprint selection: recorded branch {recorded} selected plan Sprint {selected}"
    if int(highest) != number:
        provenance += f"; highest plan heading Sprint {highest} disagrees"
    return selected, [section for raw, section in at if raw == selected], provenance


def sprint_sections(text: str) -> tuple[str, list[str]]:
    selected, sections, _provenance = select_sprint(text)
    return selected, sections
