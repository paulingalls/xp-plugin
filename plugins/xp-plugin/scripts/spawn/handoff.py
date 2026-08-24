"""Persist a stopped teammate's artifacts and hand them to its successor."""

import json
import sys
from pathlib import Path

from work import entries


def draft_path(root: Path, story_id: str) -> Path:
    return root / "plans" / f"{story_id}.plan.md"


def marker_path(root: Path, story_id: str) -> Path:
    return root / "plans" / f"{story_id}.handoff.json"


def _is_authored(text: str, story_id: str) -> bool:
    return f"\nStory: {story_id}\n" in text


READ_THEM = " Read them (`work.py list`), then fix the card or take the work over."


def _state(root: Path, story_id: str) -> dict:
    """The marker as a dict, or {} for absent, unreadable or not-an-object."""
    try:
        state = json.loads(marker_path(root, story_id).read_text())
    except (OSError, ValueError):
        return {}
    return state if isinstance(state, dict) else {}


def record_handoff(
    root: Path, story_id: str, before: set[str], why: str, rc: int
) -> tuple[int, str]:
    during = [(eid, text) for eid, text in entries(root) if eid not in before]
    authored = [eid for eid, text in during if _is_authored(text, story_id)]
    # Records ACCUMULATE, because the draft and the findings do: one filed at stop
    # 1 is in `before` at stop 2 and can never be `during` again, so overwriting
    # hands stop 3 only stop 2's words. story-028 stopped five times.
    kept = [eid for eid in _state(root, story_id).get("records", []) if eid not in authored]
    path = marker_path(root, story_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"why": why, "records": kept + authored}))
    recovery = f"\nWhat the handback guard saw: {why}"
    if rc:
        if authored:
            found = f" Teammate records: {', '.join(authored)}.{READ_THEM}"
        elif during:
            found = f" Records filed during this run: {', '.join(eid for eid, _ in during)}."
        else:
            found = ""
        return 3, f"{story_id} DIED (harness rc {rc}).{found}{recovery}"
    if not authored:
        return 2, why
    return 3, (
        f"{story_id} ESCALATED by the teammate — teammate records:"
        f" {', '.join(authored)}.{READ_THEM}{recovery}"
    )


def _findings(root: Path, story_id: str) -> list[Path]:
    plans = root / "plans"
    first = plans / f"{story_id}.md"
    rounds = sorted(
        plans.glob(f"{story_id}.round-*.md"),
        key=lambda path: int(path.stem.rsplit("-", 1)[1]),
    )
    return ([first] if first.is_file() else []) + rounds


def inheritance(root: Path, story_id: str) -> str:
    state = _state(root, story_id)
    if not state:
        return ""
    parts = [("Why the predecessor stopped", str(state.get("why", "")))]
    draft = draft_path(root, story_id)
    if draft.is_file():
        parts.append(("Predecessor plan draft", draft.read_text()))
    for path in _findings(root, story_id):
        parts.append((f"Plan-review findings: {path.name}", path.read_text()))
    indexed = dict(entries(root))
    for record_id in state.get("records", []):
        if record_id in indexed:
            parts.append((f"Predecessor escalation record: {record_id}", indexed[record_id]))
    return "\n".join(f"### {title}\n\n{body.rstrip()}\n" for title, body in parts)


def report_handoff(root: Path, story_id: str, before: set[str], why: str, rc: int) -> int:
    result, message = record_handoff(root, story_id, before, why, rc)
    print(message, file=sys.stderr)
    return result
