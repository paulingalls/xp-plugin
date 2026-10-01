"""Bounded close-history context for session recovery."""

from review_report import REPORT_KEYS, normalize_report, render_item

CLOSE_CAP = 400  # the whole close detail; see _close_detail
ROUND_CAP = 100  # per round within it


def _close_detail(record: dict) -> str:
    """Bound rounds so more of them never means fewer constraints reach the lead."""
    rounds = record.get("rounds")
    if rounds is None:  # a record older than rounds[] is MISSING them, not unreadable
        return "(no rounds in this record)"
    if not isinstance(rounds, list):
        return "(unreadable close record)"
    shown = []
    for i, r in enumerate(rounds, 1):
        parsed, error = normalize_report(r)
        if error:
            return "(unreadable close record — repair closes.jsonl)"
        items = ", ".join(
            f"{key}: {render_item(key, item)}"
            for key in REPORT_KEYS
            for item in parsed.get(key, [])
        )
        if len(items) > ROUND_CAP:
            items = items[:ROUND_CAP] + "… (in full at closes.jsonl)"
        shown.append(f"round {i}: {items or 'clean'}")
    detail = _fit(shown)
    if ("elided" in detail or "…" in detail) and "in full at closes.jsonl" not in detail:
        detail += " (in full at closes.jsonl)"
    return detail


def _fit(parts: list) -> str:
    """Joined and bounded — dropping the OLDEST parts, never the newest.

    A head-truncating cap loses the last round, and the round that gated the merge
    is at the end unless salvage recorded one out of order (overlap.py owns which).
    """
    kept, dropped = list(parts), 0
    while len(" · ".join(kept)) > CLOSE_CAP and len(kept) > 1:
        kept.pop(0)
        dropped += 1
    detail = " · ".join(kept)
    if len(detail) > CLOSE_CAP:
        detail = detail[:CLOSE_CAP] + "…"
    return f"(+{dropped} earlier elided) {detail}" if dropped else detail
