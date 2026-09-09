"""Concurrent-safe sprint marker state."""

import json
from pathlib import Path

import plan_writer
from work import data_root


def sprint_marker(sprint_id: str) -> Path:
    d = data_root() / "markers" / "sprint"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{sprint_id}.json"


def read_sprint_state(sprint_id: str) -> tuple[Path, dict, str]:
    path = sprint_marker(sprint_id)
    if not path.exists():
        return path, {}, ""
    try:
        state = json.loads(path.read_text())
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return path, {}, f"refused: unreadable sprint marker {path}: {exc}"
    if not isinstance(state, dict):
        return path, {}, f"refused: unreadable sprint marker {path}: expected a JSON object"
    return path, state, ""


def write_sprint_state(path: Path, changes, remove=()) -> dict:
    def update(current: dict) -> None:
        if callable(changes):
            changes(current)
        else:
            rounds = current.setdefault("rounds", []) if changes.get("rounds") else []
            for round_ in changes.get("rounds", []):
                if round_ not in rounds:
                    rounds.append(round_)
            current.update({key: value for key, value in changes.items() if key != "rounds"})
            for key in remove:
                current.pop(key, None)

    lock = data_root() / "locks" / f"sprint-{path.stem}.lock"
    return plan_writer.locked_json_edit(path, lock, update, "sprint marker")
