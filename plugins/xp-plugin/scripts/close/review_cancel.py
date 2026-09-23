"""Handle a stopped review without recording coverage."""

from pathlib import Path

from review_artifacts import archive_cancelled


def cancelled(story_id: str, head: str, report: Path, launch: Path, log: Path) -> int:
    import close
    import review

    saved = archive_cancelled(report, review.patch_path(report), log)
    dirty = close.git("status", "--porcelain").stdout.strip()
    why = f"CANCELLED: {story_id}'s card changed while its reviewer ran"
    if dirty:
        why += f"; uncommitted:\n  {dirty}"
    message = review.abort_text(head, why, salvage=True)
    moved = close.git("rev-parse", "HEAD").stdout.strip() != head
    if not dirty and not moved:
        launch.unlink(missing_ok=True)
    else:
        message += (
            f"\nLaunch marker retained at {launch}; inspect the saved artifacts,"
            " remove that marker, then retry land."
        )
    return close.fail(message + f"\nSaved cancelled review artifacts: {', '.join(map(str, saved))}")
