"""Emit durable evidence for LLM triage; do not classify prose or eligibility."""

import json

from overlap import unresolved_blocking
from review_report import history_digest, normalize_report
from work import _disposal, debt_reference_error, entries


def render_triage(root) -> str:
    out = [
        "Every open debt and unresolved finding: fix, explicit reasoned drop, or exceptional keep",
        "with both too-big and too-important bars restated. Notes: judge deferred findings;",
        "preserve discovery/value tradeoffs for promote/archive. Full source follows.",
    ]
    disposal = _disposal()
    judgments = {}
    records = entries(root)
    retained = {}
    for _ref, text in records:
        if text.startswith("## retained "):
            fields = dict(line.split(": ", 1) for line in text.splitlines() if ": " in line)
            if ref := fields.get("Keeps"):
                retained[ref] = text
    for ref, text in records:
        if (
            not text.startswith("## debt ")
            or disposal._archived(root, ref)
            or disposal._resolved(root, ref)
        ):
            continue
        out.append(f"Open debt {ref} ({root / 'work.md'}):\n{text.rstrip()}")
        if ref in retained:
            out.append(f"Latest retention for {ref}:\n{retained[ref].rstrip()}")
        if error := debt_reference_error(root, ref):
            out.append(f"Unusable debt {ref}: {error} — repair before judging")
    for ref, text in entries(root):
        if not text.startswith("## judgment ") or disposal._archived(root, ref):
            continue
        fields = dict(line.split(": ", 1) for line in text.splitlines() if ": " in line)
        try:
            parsed, error = normalize_report(json.loads(fields["Judgment"]))
            if error:
                raise ValueError(error)
            selected = [
                item if isinstance(item, str) else item["finding"]
                for key in ("fixed", "dropped", "debt")
                for item in parsed.get(key, [])
            ]
            judgments.setdefault((fields["Source"], fields["Digest"]), set()).update(selected)
        except (ValueError, KeyError, TypeError):
            out.append(f"Unreadable judgment {ref} in {root / 'work.md'} — repair before judging")
    histories = []
    log = root / "closes.jsonl"
    if log.exists():
        for number, line in enumerate(log.read_text().splitlines(), 1):
            try:
                record = json.loads(line)
                histories.append((f"{log.resolve()}:{number}", record["rounds"]))
            except (ValueError, KeyError, TypeError):
                out.append(f"Unreadable close history at {log}:{number} — repair before judging")
    for path in (root / "markers").rglob("*.json"):
        try:
            state = json.loads(path.read_text())
        except (ValueError, OSError, UnicodeError) as error:
            out.append(f"Unreadable marker {path}: {error} — repair before judging")
            continue
        if isinstance(state, dict) and "rounds" in state:
            histories.append((str(path.resolve()), state["rounds"]))
    for source, rounds in histories:
        if not isinstance(rounds, list):
            out.append(f"Unreadable rounds at {source} — repair before judging")
            continue
        pending, readable = {}, []
        for number, raw in enumerate(rounds, 1):
            parsed, error = normalize_report(raw)
            if error:
                out.append(f"Unreadable round {number} at {source}: {error}")
                continue
            readable.append(raw)
            for key in ("fixed", "dropped", "debt"):
                for item in parsed.get(key, []):
                    pending.pop(item if isinstance(item, str) else item["finding"], None)
            for item in parsed.get("legacy_untriaged", []):
                pending[item] = f"legacy/untriaged: {item}"
        pending.update(
            (item, f"blocking: {item}") for item in unresolved_blocking({"rounds": readable})
        )
        out.extend(
            f"Unresolved finding ({source}): {shown}"
            for finding, shown in pending.items()
            if shown.startswith("blocking:")
            or finding not in judgments.get((source, history_digest(rounds)), set())
        )
    return "\n".join(out)
