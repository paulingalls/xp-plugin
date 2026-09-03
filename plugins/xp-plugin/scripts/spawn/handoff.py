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
STAGES = ("planner", "plan-reviewer", "executor", "reviewer")
# Shared so a new result cannot pass the writer and red the reader: mark_stage
# and resume.validate spelled ("ran", "skipped") separately until story-102.
RESULTS = ("ran", "skipped", "blocked")


def handoff_state(root: Path, story_id: str) -> dict | None:
    """The marker as a dict, {} for absent OR empty, None for present-but-unreadable.

    A caller that must tell absent from empty stats the path. Absent and unreadable are
    different problems with different fixes, and this is the one file where conflating
    them is silent: {} means "first spawn ever", so a truncated marker threw away a
    draft, its findings and the escalation record that were all readable on disk beside
    it — the whole inheritance, and no refusal, because the successor cannot miss what
    it was never told exists.
    """
    path = marker_path(root, story_id)
    if not path.exists():
        return {}
    try:
        state = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    return state if isinstance(state, dict) else None


def _write(root: Path, story_id: str, state: dict) -> None:
    path = marker_path(root, story_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".json.part")
    temp.write_text(json.dumps(state))
    temp.replace(path)


def record_handoff(
    root: Path, story_id: str, before: set[str], why: str, rc: int
) -> tuple[int, str]:
    during = [(eid, text) for eid, text in entries(root) if eid not in before]
    authored = [eid for eid, text in during if _is_authored(text, story_id)]
    # Records ACCUMULATE, because the draft and the findings do: one filed at stop
    # 1 is in `before` at stop 2 and can never be `during` again, so overwriting
    # hands stop 3 only stop 2's words. story-028 stopped five times.
    previous = handoff_state(root, story_id) or {}
    kept = [eid for eid in previous.get("records", []) if eid not in authored]
    # Written whole and MOVED into place: a stop interrupted mid-write is how the
    # unreadable marker above gets made, and this is its one producer.
    previous.update(state="STOPPED", why=why, records=kept + authored)
    _write(root, story_id, previous)
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


def mark_handoff(root: Path, story_id: str, finished: bool = False) -> None:
    state = handoff_state(root, story_id) or {}
    kind = "FINISHED" if finished else "RUNNING"
    state.update(state=kind, why=f"the teammate is {kind.lower()}")
    _write(root, story_id, state)


def mark_stage(root: Path, story_id: str, stage: str, result: str) -> None:
    if stage not in STAGES or result not in RESULTS:
        raise ValueError(f"invalid spawn stage {stage}={result}")
    state = handoff_state(root, story_id) or {}
    state.setdefault("stages", {})[stage] = result
    _write(root, story_id, state)


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
    if not marker.exists():
        return ""  # no marker: a first spawn inherits nothing and says nothing
    state = handoff_state(root, story_id)
    if state is None:
        label = "UNREADABLE"
        why = (
            f"{marker} is unreadable, so the records the predecessor"
            " filed cannot be listed here — read them with `work.py list`."
            " What survived on disk follows."
        )
        state = {}
    else:
        label = str(state.get("state", "INVALID"))
        why = str(state.get("why", ""))
    parts = [(f"Predecessor handback — {label}", why)]
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
