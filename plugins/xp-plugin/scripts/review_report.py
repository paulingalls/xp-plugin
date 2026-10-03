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
    if fresh and "legacy_untriaged" in data:
        return {}, "legacy/untriaged report cannot certify a new round"
    historical = not fresh and ("noted" in data or "legacy_untriaged" in data)
    required = ("actionable", "blocking") if stage == "solution" else ("blocking",)
    missing = [key for key in required if not isinstance(data.get(key), list)]
    if missing:
        return {}, f"the {stage or 'reviewer'} report is missing list keys: {', '.join(missing)}"
    if fresh and stage and stage != "solution" and data.get("actionable"):
        return {}, f"the {stage} report must put unresolved actionable findings in blocking"
    for key in required:
        if not isinstance(data.get(key), list):
            return {}, f"the {stage or 'reviewer'} report is missing list keys: {key}"
        if not all(isinstance(item, str) and (historical or item.strip()) for item in data[key]):
            return {}, f"{key} must contain non-empty finding text"
    for key in ("fixed", "dropped", "debt", "actionable", "legacy_untriaged", "noted"):
        if key in data and not isinstance(data[key], list):
            return {}, f"{key} must be a list"
    if "fixed" in data and not all(isinstance(item, str) for item in data["fixed"]):
        return {}, "fixed must contain finding text"
    for key, fields in (
        ("dropped", ("finding", "reason")),
        ("debt", ("finding", "ref", "too_big", "too_important")),
    ):
        for item in data.get(key, []):
            if isinstance(item, dict):
                if not all(
                    isinstance(item.get(field), str) and item[field].strip() for field in fields
                ):
                    return {}, f"{key} needs nonempty {', '.join(fields)}"
                if fresh and key == "debt":
                    from work import data_root, debt_reference_error

                    if error := debt_reference_error(data_root(), item["ref"]):
                        return {}, error
            else:
                return {}, f"{key} needs an explained disposition with {', '.join(fields)}"
    report = dict(data)
    if "noted" in report:
        if fresh:
            return {}, "legacy/untriaged report cannot certify a new round"
        report["legacy_untriaged"] = report.pop("noted")
    _, _, error = validate_clearable(report, stage)
    if error:
        return {}, error
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


def parse_report_json(text: str):
    return json.loads(text, object_pairs_hook=_unique_fields)


def read_report(path: Path, stage: str = "", *, fresh=True) -> tuple[dict, str]:
    try:
        data = parse_report_json(path.read_text())
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
    result = {}
    for key in REPORT_KEYS:
        if not any(key in report for report in reports):
            continue
        items = [item for report in reports for item in report.get(key, [])]
        if key == "blocking" and blockers:
            result[key] = items
        else:
            seen = {}
            for item in items:
                seen.setdefault(identity(item), item)
            if items or any(key in report for report in reports):
                result[key] = list(seen.values())
    return result


def render_item(key: str, item) -> str:
    if key == "dropped" and isinstance(item, dict):
        return f"{item['finding']} — dropped: {item['reason']}"
    if key == "debt" and isinstance(item, dict):
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
