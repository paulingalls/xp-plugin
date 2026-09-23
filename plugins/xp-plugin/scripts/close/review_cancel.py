"""Handle a stopped review without recording coverage."""

from pathlib import Path

from review_artifacts import archive_cancelled
from review_card import card_now


def card_changed(story_id: str, card: str):
    """A plan read mid-write can cut this card short and look edited, so a cancel
    needs the same differing card on two consecutive polls."""
    seen = [""]

    def changed() -> bool:
        now = card_now(story_id)
        agreed = bool(now) and now != card and now == seen[0]
        seen[0] = now
        return agreed

    return changed


def cancelled(story_id: str, head: str, digest: str, report: Path, launch: Path, log: Path) -> int:
    import close
    import review

    saved = archive_cancelled(report, review.patch_path(report), log)
    dirty = close.git("status", "--porcelain").stdout.strip()
    why = f"CANCELLED: {story_id}'s card changed while its reviewer ran"
    if dirty:
        why += f"; uncommitted:\n  {dirty}"
    marker = close.marker_path(story_id)
    marker_changed = review.marker_digest(marker) != digest
    if marker_changed:
        why += f"; close marker changed during the review ({marker})"
    message = review.abort_text(head, why, salvage=True)
    moved = close.git("rev-parse", "HEAD").stdout.strip() != head
    if not dirty and not moved and not marker_changed:
        launch.unlink(missing_ok=True)
    else:
        message += (
            f"\nLaunch marker retained at {launch}; inspect the saved artifacts,"
            " remove that marker, then retry land."
        )
    return close.fail(message + f"\nSaved cancelled review artifacts: {', '.join(map(str, saved))}")
