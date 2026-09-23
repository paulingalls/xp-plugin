"""Concurrent-safe sprint marker state."""

import json
import math
from datetime import datetime
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


HISTORY_KEYS = {
    "leg",
    "outcome",
    "command",
    "tree",
    "head",
    "started_at",
    "ended_at",
    "duration_seconds",
}


def read_tier_history(state: dict, declared_legs=()) -> tuple[list[dict] | None, str]:
    if "full_tier_history" not in state:
        return None, ""
    history = state["full_tier_history"]
    if not isinstance(history, list):
        return None, "unreadable full_tier_history"
    for index, entry in enumerate(history, 1):
        valid = isinstance(entry, dict) and set(entry) == HISTORY_KEYS
        if valid:
            valid = (
                entry["leg"] in ("land", *declared_legs)
                and entry["outcome"] in ("passed", "failed", "reused")
                and all(
                    isinstance(entry[key], str) and entry[key]
                    for key in ("command", "tree", "head", "started_at", "ended_at")
                )
                and type(entry["duration_seconds"]) in (int, float)
                and math.isfinite(entry["duration_seconds"])
                and entry["duration_seconds"] >= 0
            )
        if valid:
            try:
                start = datetime.fromisoformat(entry["started_at"].replace("Z", "+00:00"))
                end = datetime.fromisoformat(entry["ended_at"].replace("Z", "+00:00"))
                valid = (
                    start.utcoffset().total_seconds() == end.utcoffset().total_seconds() == 0
                    and end >= start
                )
            except (ValueError, AttributeError):
                valid = False
        if not valid:
            return None, f"unreadable full_tier_history entry {index}"
    return history, ""


LATEST_FAILED = "latest outcome failed"


def reuse_veto(history: list[dict], tree: str, command: str, head: str) -> str:
    """Why a receipt matching `tree` may not be reused; only the LATEST outcome for a
    tree counts, so a superseded pass is never re-promoted."""
    latest = next((item for item in reversed(history) if item["tree"] == tree), None)
    if latest is None:
        return "receipt has no matching history entry"
    if latest["outcome"] == "failed":
        return LATEST_FAILED
    if latest["command"] != command or latest["head"] != head:
        return "receipt contradicts full_tier_history"
    return ""


def leg_reuse_veto(history: list[dict], event: dict) -> str:
    latest = next(
        (
            item
            for item in reversed(history)
            if (item["leg"], item["command"], item["tree"])
            == (event["leg"], event["command"], event["tree"])
        ),
        None,
    )
    if latest is None:
        return "leg receipt has no matching history entry"
    if latest["outcome"] == "failed":
        return LATEST_FAILED
    if latest["head"] != event["head"]:
        return "leg receipt contradicts full_tier_history"
    return ""


def append_tier_evidence(path: Path, event: dict, receipt: dict | None, declared_legs=()) -> dict:
    def update(current: dict) -> None:
        history, error = read_tier_history(current, declared_legs)
        if error:
            raise ValueError(error)
        if event["outcome"] == "reused" and history is not None:
            veto = (
                leg_reuse_veto(history, event)
                if event["leg"] in declared_legs
                else reuse_veto(history, event["tree"], event["command"], event["head"])
            )
        else:
            veto = ""
        if veto:
            raise ValueError(veto)
        current["full_tier_history"] = [*(history or []), event]
        if receipt is not None:
            current["full_tier"] = receipt

    return write_sprint_state(path, update)
