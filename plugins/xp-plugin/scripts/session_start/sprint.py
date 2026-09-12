import contextlib
import io
import json
import re
from pathlib import Path

from env import data_root, sprint_branch, sprint_branch_name, sprint_id_value


class SprintSelectionError(RuntimeError):
    pass


def release_state(sprint: str) -> tuple[str, Path]:
    expected = sprint_id_value(sprint)
    path = data_root() / "releases" / f"sprint-{expected}.json"
    try:
        record = json.loads(path.read_text())
    except FileNotFoundError:
        return "missing", path
    except (OSError, UnicodeError, ValueError):
        return "unreadable", path
    valid = (
        isinstance(record, dict)
        and type(record.get("sprint")) is type(expected)
        and record["sprint"] == expected
        and isinstance(record.get("merged_sha"), str)
        and bool(record["merged_sha"])
        and (
            record.get("tag") is None
            or (isinstance(record.get("tag"), str) and bool(record["tag"]))
        )
    )
    return ("released" if valid else "unreadable"), path


def slate_review_marker(sprint: str) -> Path:
    return data_root() / "markers" / f"{sprint_id_value(sprint)}.slate-review-incomplete"


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
        if (match := re.match(r"### Sprint (\S*\w)", section))
    ]
    recorded = _recorded_branch()
    if not recorded:
        if all(raw.isdigit() for raw, _section in at):
            selected = max((raw for raw, _section in at), key=int, default="")
            choice = f"highest-numbered fallback selected plan Sprint {selected}"
        else:
            selected = at[-1][0]
            choice = (
                f"last-heading fallback selected plan Sprint {selected} because a non-numeric "
                "Sprint id is present"
            )
        provenance = f"sprint selection: no sprint branch recorded; {choice}"
        return selected, [section for raw, section in at if raw == selected], provenance
    if not recorded.startswith("sprint-"):
        raise SprintSelectionError(f"recorded branch {recorded} is not named sprint-N")
    selected = next((raw for raw, _section in at if sprint_branch_name(raw) == recorded), "")
    if not selected:
        available = ", ".join(f"Sprint {raw}" for raw, _section in at) or "none"
        raise SprintSelectionError(
            f"recorded branch {recorded} has no matching heading in the plan; "
            f"available headings: {available}"
        )
    provenance = f"sprint selection: recorded branch {recorded} selected plan Sprint {selected}"
    numeric = [raw for raw, _section in at if raw.isdigit()]
    highest = max(numeric, key=int, default="")
    if highest and sprint_branch_name(highest) != recorded:
        provenance += f"; highest plan heading Sprint {highest} disagrees"
    sections = [section for raw, section in at if sprint_branch_name(raw) == recorded]
    return selected, sections, provenance


def sprint_sections(text: str) -> tuple[str, list[str]]:
    selected, sections, _provenance = select_sprint(text)
    return selected, sections
