"""One report contract for fresh acceptance and historical disposition readers."""

import hashlib
import json
from pathlib import Path

SCHEMA = 2
REPORT_KEYS = ("fixed", "blocking", "dropped", "debt", "legacy_untriaged")
NEW_KEYS = REPORT_KEYS[:-1]
CLEARABLE_BY_FULL = "clearable_by_full"
NO_ROUND = "No round was recorded."
ITEM_CAP = 400
LIST_CAP = 20


def empty_report() -> dict:
    return {"schema": SCHEMA, **{key: [] for key in NEW_KEYS}}


def _line(value) -> bool:
    return isinstance(value, str) and bool(value.strip()) and len(value.splitlines()) == 1


def normalize_report(data, *, fresh=False, stage="") -> tuple[dict, str]:
    if not isinstance(data, dict):
        return {}, "the reviewer's report is JSON but not an object"
    version = data.get("schema")
    legacy = "schema" not in data
    historical_legacy = legacy or (not fresh and "legacy_untriaged" in data)
    keys = ("fixed", "blocking", "noted") if legacy else NEW_KEYS
    if legacy and any(key in data for key in ("dropped", "debt", "legacy_untriaged")):
        return {}, "unversioned report has disposition fields — restore its schema"
    if not legacy and (type(version) is not int or version != SCHEMA or "noted" in data):
        return {}, "unknown or mixed report schema — write schema 2 without noted"
    missing = [key for key in keys if not isinstance(data.get(key), list)]
    if missing:
        return {}, f"the reviewer's report is missing list keys: {', '.join(missing)}"
    for key in keys:
        if key in ("dropped", "debt"):
            fields = (
                ("finding", "reason")
                if key == "dropped"
                else ("finding", "ref", "too_big", "too_important")
            )
            for item in data[key]:
                if (
                    not isinstance(item, dict)
                    or set(item) != set(fields)
                    or not all(_line(item.get(field)) for field in fields)
                ):
                    return {}, f"{key} requires non-empty single-line {', '.join(fields)}"
                if key == "debt" and fresh:
                    from work import data_root, debt_reference_error

                    if error := debt_reference_error(data_root(), item["ref"]):
                        return {}, error
        elif not all(
            isinstance(item, str) and (historical_legacy or _line(item)) for item in data[key]
        ):
            shape = "strings" if historical_legacy else "non-empty single-line strings"
            return {}, f"{key} must contain {shape}"
    if legacy and fresh:
        return {}, "legacy/untriaged report cannot certify a new round — judge and write schema 2"
    if "legacy_untriaged" in data:
        items = data["legacy_untriaged"]
        if fresh or not isinstance(items, list) or not all(isinstance(item, str) for item in items):
            return {}, "legacy_untriaged is historical evidence only — judge it in a new report"
    _, _, error = validate_clearable(data, stage)
    if error:
        return {}, error
    if legacy:
        report = empty_report() | {key: data[key] for key in ("fixed", "blocking")}
        report["legacy_untriaged"] = data["noted"]
    else:
        report = {"schema": SCHEMA, **{key: data[key] for key in NEW_KEYS}}
        if "legacy_untriaged" in data:
            report["legacy_untriaged"] = data["legacy_untriaged"]
    if stage == "closer" or (not fresh and CLEARABLE_BY_FULL in data):
        report[CLEARABLE_BY_FULL] = data.get(CLEARABLE_BY_FULL, [])
    return report, ""


def validate_clearable(data: dict, stage: str = "") -> tuple[list[str], list[str], str]:
    if not stage or CLEARABLE_BY_FULL not in data:
        return [], [], ""
    if stage != "closer":
        return [], [], f"the {stage} report may not contain {CLEARABLE_BY_FULL}"
    bound = data[CLEARABLE_BY_FULL]
    legacy = "schema" not in data or "legacy_untriaged" in data
    if not isinstance(bound, list) or not all(
        isinstance(item, str) and (legacy or _line(item)) for item in bound
    ):
        return [], [], f"the closer report's {CLEARABLE_BY_FULL} must be a list of strings"
    remaining = list(data["blocking"])
    for item in bound:
        if item not in remaining:
            return (
                [],
                [],
                f"the closer report's {CLEARABLE_BY_FULL} names no matching blocker: {item}",
            )
        remaining.remove(item)
    return bound, remaining, ""


def _unique_fields(pairs):
    report = {}
    for key, value in pairs:
        if key in report:
            raise ValueError(f"duplicate report field: {key}")
        report[key] = value
    return report


def read_report(path: Path, stage: str = "", *, fresh=True) -> tuple[dict, str]:
    try:
        data = json.loads(path.read_text(), object_pairs_hook=_unique_fields if fresh else None)
    except FileNotFoundError:
        return (
            {},
            f"the reviewer wrote no report at {path}; only what it printed survives. {NO_ROUND}",
        )
    except (OSError, UnicodeError) as error:
        return {}, f"could not read reviewer report {path} ({error})"
    except ValueError as error:
        return {}, f"the reviewer's report is not JSON ({error})"
    report, error = normalize_report(data, fresh=fresh, stage=stage)
    return report, f"{error}. Repair the report before recording it. {NO_ROUND}" if error else ""


def identity(item) -> str:
    return json.dumps(item, sort_keys=True, ensure_ascii=False)


def aggregate(reports, *, blockers=True) -> dict:
    result = empty_report()
    for key in REPORT_KEYS:
        items = [item for report in reports for item in report.get(key, [])]
        if key == "blocking" and blockers:
            result[key] = items
        else:
            seen = {}
            for item in items:
                seen.setdefault(identity(item), item)
            if items or key in NEW_KEYS:
                result[key] = list(seen.values())
    return result


def render_item(key: str, item) -> str:
    if key == "dropped":
        return f"{item['finding']} — dropped: {item['reason']}"
    if key == "debt":
        return (
            f"{item['finding']} — debt {item['ref']}; too big: {item['too_big']}; "
            f"too important: {item['too_important']}"
        )
    return item


def cap_items(items: list) -> list:
    return [item if len(item) <= ITEM_CAP else item[: ITEM_CAP - 1] + "…" for item in items]


def cap_display(items: list, path: Path) -> list:
    kept = [
        item if len(item) <= ITEM_CAP else f"{item[:ITEM_CAP]}… (in full at {path})"
        for item in items[:LIST_CAP]
    ]
    return _cap_list(kept, len(items), path)


def _cap_list(kept: list, total: int, path: Path) -> list:
    if total > LIST_CAP:
        kept[-1] = f"(+{total - LIST_CAP + 1} more, in full at {path})"
    return kept


def cap_dispositions(key: str, items: list, path: Path) -> list:
    shown = []
    for item in items[:LIST_CAP]:
        full = render_item(key, item)
        if len(full) > ITEM_CAP:
            clipped = {
                field: value if len(value) <= 100 else value[:100] + "…"
                for field, value in item.items()
            }
            full = f"{render_item(key, clipped)} (in full at {path})"
        shown.append(full)
    return _cap_list(shown, len(items), path)


def history_digest(rounds: list) -> str:
    return hashlib.sha256(identity(rounds).encode()).hexdigest()
