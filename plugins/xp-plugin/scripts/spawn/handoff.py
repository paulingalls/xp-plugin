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


def record_handoff(
    root: Path, story_id: str, before: set[str], why: str, rc: int
) -> tuple[int, str]:
    after = entries(root)
    during = [(eid, text) for eid, text in after if eid not in before]
    authored = [eid for eid, text in during if _is_authored(text, story_id)]
    path = marker_path(root, story_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"why": why, "records": authored}))
    recovery = f"\nWhat the handback guard saw: {why}"
    if rc:
        records = f" Teammate records: {', '.join(authored)}." if authored else ""
        concurrent = (
            f" Records filed during this run: {', '.join(eid for eid, _ in during)}."
            if during and not authored
            else ""
        )
        return 3, f"{story_id} DIED (harness rc {rc}).{records}{concurrent}{recovery}"
    if not authored:
        return 2, why
    return 3, (
        f"{story_id} ESCALATED by the teammate — teammate records: {', '.join(authored)}."
        f" Read them (`work.py list`), then fix the card or take the work over.{recovery}"
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
    marker = marker_path(root, story_id)
    if not marker.is_file():
        return ""
    try:
        state = json.loads(marker.read_text())
    except (OSError, ValueError):
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
    print(message if result == 3 else why, file=sys.stderr)
    return result
