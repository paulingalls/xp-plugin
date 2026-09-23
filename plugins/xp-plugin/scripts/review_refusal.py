"""Review-refusal text and recovery guidance."""

import contextlib
import subprocess
import tempfile
from pathlib import Path

from env import data_root
from review_report import NO_ROUND


def _save_dirty_patch(reviewed_head: str) -> tuple[Path | None, str]:
    path = None
    try:
        # Bytes, not close.git: text mode folds CRLF and raises on a non-UTF-8 line,
        # and either way the one copy the reset is about to destroy no longer applies.
        diff = subprocess.run(
            ["git", "diff-index", "-p", "--binary", reviewed_head, "--"],
            capture_output=True,
            check=True,
        ).stdout
        if not diff:  # untracked alone: the reset keeps them, and git apply refuses empty input
            return None, ""
        reports = data_root() / "reports"
        reports.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            "wb",
            dir=reports,
            prefix=f"review-refusal-{reviewed_head[:8]}-",
            suffix=".patch",
            delete=False,
        ) as file:
            path = Path(file.name)
            file.write(diff)
    except (OSError, subprocess.CalledProcessError) as exc:
        if path:
            with contextlib.suppress(OSError):
                path.unlink()
        return None, str(exc)
    return path, ""


def abort_text(reviewed_head: str, why: str, recorded: str = NO_ROUND, salvage=False) -> str:
    """EVERY abort in the review leg, not only the motion checks: a refused run can still have
    left commits behind. Salvage never offers an undo after HEAD moved because it
    cannot attribute that motion to a reviewer.
    `recorded` is what became of the round: a leg that records one before refusing must not offer
    the undo under a sentence saying it did not — and the reset may be what orphans the sha.
    """
    from close import git

    moved = git("rev-parse", "HEAD").stdout.strip() != reviewed_head
    dirty = git("status", "--porcelain").stdout.strip()
    if not moved and (salvage or not dirty):
        return f"refused: {why}" if recorded == NO_ROUND else f"refused: {why}\n\n{recorded}"
    stat = git("diff", "--stat", f"{reviewed_head}..HEAD").stdout
    if salvage and moved:
        commits = git("log", "--format=%h %s", f"{reviewed_head}..HEAD").stdout
        saved = ""
        if dirty:
            patch, error = _save_dirty_patch(reviewed_head)
            saved = (
                f"\nRecovery patch: {patch}"
                if patch
                else (f"\nRecovery patch could not be saved: {error}")
            )
        return (
            f"refused: {why}\n\nCommits since launch {reviewed_head[:8]}:\n{commits}"
            f"{stat}\n{recorded}{saved}\nInspect the saved report and patch and these commits."
            " Remove the named launch marker, then retry land."
        )
    saved = ""
    if dirty:
        patch, error = _save_dirty_patch(reviewed_head)
        if error:
            return (
                f"refused: {why}\n\n{stat}\n{recorded} The reviewer's work remains in your"
                f" tree, but it could not save a recovery patch ({error}). No destructive"
                " recovery is offered."
            )
        if patch:
            saved = (
                f" Saved the staged and unstaged work at {patch}; after restoring"
                f" {reviewed_head[:8]}, recover it with git apply {patch}."
            )
    return (
        f"refused: {why}\n\n{stat}\n{recorded}{saved} The reviewer's work is in your tree —"
        f" yours to keep or undo: git reset --hard {reviewed_head[:8]}"
    )
