"""Read the explicit disposition and preserve independent plan reasons."""

import json
import re


def normalized_words(text: str) -> str:
    """The word stream both artifacts share, so a reason compares by content.

    Naming the markers to strip is the rejected design — it fixed the blockquote
    and left the backtick. Dropping every non-word run ignores presentation as a
    class; the words and their order must still match, so a reason absent from the
    plan, or written there in other words, refuses.
    """
    return " ".join(re.findall(r"\w+", text))


def _unique_fields(pairs: list[tuple[str, object]]) -> dict:
    report = {}
    for key, value in pairs:
        if key in report:
            raise ValueError(f"duplicate disposition field: {key}")
        report[key] = value
    return report


def _bare_objects(text: str) -> tuple[list[dict], bool]:
    decoder = json.JSONDecoder(object_pairs_hook=_unique_fields)
    objects, end, failed = [], 0, False
    for start in (i for i, char in enumerate(text) if char == "{"):
        if start < end:
            continue
        try:
            value, end = decoder.raw_decode(text, start)
        except ValueError:
            failed = True
            continue
        if isinstance(value, dict):
            objects.append(value)
    return objects, failed


def disposition_object(text: str) -> tuple[dict | None, str]:
    try:
        report = json.loads(text, object_pairs_hook=_unique_fields)
    except ValueError:
        values, failed, masked = [], False, list(text)
        fences = list(re.finditer(r"```([^\n]*)\n(.*?)```", text, flags=re.S))
        for fence in fences:
            language, body = fence.group(1).strip().lower(), fence.group(2)
            candidate = language == "json" or body.lstrip().startswith(("{", "["))
            if not candidate:
                continue
            for index in range(fence.start(), fence.end()):
                masked[index] = " "
            try:
                values.append(json.loads(body, object_pairs_hook=_unique_fields))
            except ValueError:
                objects, malformed = _bare_objects(body)
                values.extend(objects)
                failed |= malformed or not objects
                continue
        objects, malformed = _bare_objects("".join(masked))
        # BEFORE the extend, so `values` is still only what the FENCES gave: the charter
        # mandates a fenced verdict, so a brace in the prose beside one is prose, not a
        # rival the harness failed to read. Ungate this and `{'a': 1}` quoted in a finding
        # loses a complete review — the class this gate exists to close.
        failed |= malformed and not values
        values.extend(objects)
        # A non-object in a fence is no rival verdict — kept only when none is an object,
        # so a fenced `[]` refuses by TYPE. Narrowing either discards a completed round.
        values = [v for v in values if isinstance(v, dict)] or values
        if len(values) > 1:
            return None, (
                "the plan review wrote an ambiguous disposition — write exactly one JSON object"
            )
        if failed:
            return None, (
                "the plan review wrote a structured disposition the harness could not read"
                " — write exactly one fenced json object"
            )
        if len(values) == 1:
            report = values[0]
        else:
            return None, "the plan review wrote no structured disposition"
    if not isinstance(report, dict):
        return None, "the plan disposition must be a JSON object"
    return report, ""


def disposition_fields(report: dict) -> tuple[str, str | None, str]:
    status = report.get("status")
    if not isinstance(status, str) or status not in {"clean", "edited", "blocked"}:
        return "", None, "plan disposition status must be clean, edited, or blocked"
    if "question" in report:
        return "", None, f"legacy question is not valid new output: {report['question']}"
    if "human_question" not in report:
        return "", None, "plan disposition must carry explicit human_question"
    question = report["human_question"]
    if question is not None and (not isinstance(question, str) or not question.strip()):
        return "", None, "human_question must be null or a non-empty string"
    if status == "blocked" and question is None:
        return "", None, "blocked disposition requires a human_question"
    reasons = report.get("reasons")
    if not isinstance(reasons, list):
        return "", None, "plan reasons must be a JSON list"
    if any(not isinstance(r, str) or not normalized_words(r) for r in reasons):
        return "", None, "every plan edit must carry its reason in the plan file"
    return status, question, ""


def evaluate_disposition(
    text: str,
    before: bytes | None,
    after: bytes | None,
    before_card: str = "",
    after_card: str = "",
) -> tuple[str, str]:
    report, problem = disposition_object(text)
    if not problem:
        status, question, problem = disposition_fields(report)
    repair = " — repair the disposition and plan, then rerun the plan review"
    if problem:
        return "failed", problem + repair
    changed = before != after or before_card != after_card
    reasons = report["reasons"]
    if status == "clean" and changed:
        problem = "a clean review changed the plan"
    elif status == "edited" and not changed:
        problem = "an edited disposition left the plan unchanged"
    elif not changed and reasons:
        problem = "edit reasons reported but the plan is unchanged"
    elif changed:
        plan = f" {normalized_words((after or b'').decode(errors='replace'))} "
        if not reasons or not all(f" {normalized_words(r)} " in plan for r in reasons):
            problem = "every plan edit must carry its reason in the plan file"
    if problem:
        return "failed", problem + repair
    if question is not None:
        return (
            "blocked",
            f"blocked for the human: {question} — answer in the card, amend, then resume",
        )
    return "ran", ""


def durable_disposition(text: str) -> tuple[str, str]:
    report, problem = disposition_object(text)
    if problem:
        return "failed", problem
    if "human_question" not in report:
        status = report.get("status")
        if status == "blocked":
            question = report.get("question")
            if isinstance(question, str) and question.strip():
                return "blocked", f"blocked for the human: {question}"
            return "failed", "legacy blocked disposition requires a question"
        if status in ("clean", "edited") and "question" not in report:
            report = report | {"human_question": None, "reasons": report.get("reasons", [])}
    status, question, problem = disposition_fields(report)
    if problem:
        return "failed", problem
    if question is not None:
        return "blocked", f"blocked for the human: {question}"
    return "ran", ""
