import json
from pathlib import Path

REPORT_KEYS = ("fixed", "blocking", "noted")
NO_ROUND = "No round was recorded."
ITEM_CAP = 400
LIST_CAP = 20


def cap_items(items: list) -> list:
    return [i if len(i) <= ITEM_CAP else i[: ITEM_CAP - 1] + "…" for i in items]


def cap_display(items: list, path: Path) -> list:
    kept = cap_items(items[:LIST_CAP])
    if len(items) > LIST_CAP:
        # A display elision must point to the full durable report.
        kept[-1] = f"(+{len(items) - LIST_CAP + 1} more, in full at {path})"
    return kept


def _report_data(path: Path) -> tuple[dict, str]:
    if not path.exists():
        message = f"the reviewer wrote no report at {path} — nothing it found can be"
        return {}, f"{message} recorded; only what it printed survives. {NO_ROUND}"
    try:
        data = json.loads(path.read_text())
    except OSError as e:
        return {}, f"could not read reviewer report {path} ({e})"
    except ValueError as e:
        return {}, f"the reviewer's report is not JSON ({e})"
    if not isinstance(data, dict):
        return {}, f"the reviewer's report is JSON but not an object: got {type(data).__name__}"
    missing = [k for k in REPORT_KEYS if not isinstance(data.get(k), list)]
    if missing:
        return {}, f"the reviewer's report is missing list keys: {', '.join(missing)}"
    return data, ""


def read_report(path: Path) -> tuple[dict, str]:
    """Parse and cap a report; a reviewer under bypass can still forge its path."""
    data, error = _report_data(path)
    if error:
        return {}, error
    return {k: cap_items([str(i) for i in data[k]]) for k in REPORT_KEYS}, ""
