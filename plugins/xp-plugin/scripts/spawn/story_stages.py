import subprocess
from pathlib import Path

REVIEW_REFUSAL_TAIL = 2000


def _review_stash(git, story_id: str) -> str:
    listed = git("stash", "list", "--format=%H%x00%gs", check=False)
    if listed.returncode:
        return ""
    suffix = f": {story_id}"
    for line in listed.stdout.splitlines():
        sha, separator, subject = line.partition("\0")
        if separator and subject.endswith(suffix):
            return sha
    return ""


def _stash_selector(git, entry: str) -> str | None:
    """The entry's current `stash@{n}`, "" when the stack no longer holds it, None
    when the stack could not be read — a leak the caller must not report as a drop."""
    listed = git("stash", "list", "--format=%H%x00%gd", check=False)
    if listed.returncode:
        return None
    for line in listed.stdout.splitlines():
        sha, separator, selector = line.partition("\0")
        if separator and sha == entry:
            return selector
    return ""


def _already_restored(git, entry: str) -> bool:
    shown = git("stash", "show", "-p", "--binary", "--include-untracked", entry, check=False)
    if shown.returncode:
        return False
    return (
        subprocess.run(
            ["git", "apply", "--reverse", "--check"],
            input=shown.stdout,
            capture_output=True,
            text=True,
        ).returncode
        == 0
    )


def _drop_stash(git, entry: str) -> bool:
    selector = _stash_selector(git, entry)
    if selector is None:
        return False
    return not selector or git("stash", "drop", "-q", selector, check=False).returncode == 0


def run_planner(story_id: str, card: str, tree: Path, handoff: str) -> tuple[int, str]:
    import review
    from handback import tree_state
    from handoff import draft_path
    from spawn import PLUGIN_ROOT, build_prompt, data_root, teammate_sections

    draft = draft_path(data_root(), story_id)
    before = draft.read_bytes() if draft.is_file() else None
    sections = teammate_sections(
        card, story_id, handoff, PLUGIN_ROOT, brief=review.charter("planner")
    )
    head = tree_state(tree)
    _result, error = review.run(build_prompt(sections), tree, name="planner", card=card)
    after = draft.read_bytes() if draft.is_file() else None
    if error:
        return 2, f"the planner stage stopped: {error}"
    if tree_state(tree) != head:
        return 2, "the planner changed the repository; it owns only the external plan"
    if not after or after == before or not after.strip():
        return 2, f"the planner did not write a new non-empty plan at {draft}"
    return 0, ""


def review_story(tree: Path, story_id: str) -> tuple[int, dict, str]:
    import contextlib
    import io
    import json
    import sys

    from close import cmd_review, git, marker_path
    from work import data_root

    stderr = sys.stderr

    class Tee(io.StringIO):
        def write(self, text):
            stderr.write(text)
            return super().write(text)

    refusal = Tee()
    with contextlib.chdir(tree):
        # By SHA: refs/stash is one stack per clone, so a pop takes whoever pushed last.
        dirty = bool(git("status", "--porcelain").stdout.strip())
        if dirty and git("stash", "push", "-qu", "-m", story_id, check=False).returncode:
            return 2, {}, "the diff review could not preserve the dirty tree"
        entry = _review_stash(git, story_id) if dirty else ""
        if dirty and not entry:
            return 2, {}, "the diff review could not identify its dirty-tree entry in refs/stash"
        preserved = dropped = False
        try:
            with contextlib.redirect_stderr(refusal):
                rc = cmd_review(story_id)
            state = json.loads(marker_path(story_id).read_text()) if not rc else {}
        finally:
            # Restore AND drop inside the finally: a review that raises — a kill, an
            # unreadable marker — otherwise unwinds past the drop and leaks the entry
            # it pushed onto the stack every other worktree shares.
            if dirty:
                restored = git("stash", "apply", "-q", entry, check=False)
                preserved = bool(restored.returncode) and not _already_restored(git, entry)
                dropped = preserved or _drop_stash(git, entry)
        if preserved:
            return (
                2,
                {},
                "the diff review completed, but its dirty-tree restore failed; this is not a"
                f" review refusal. The change remains in refs/stash at {entry}",
            )
        if dirty and not dropped:
            # LOUD, not fatal. A leaked entry is the nuisance this leg exists to stop;
            # throwing away a review that ran and was recorded, to report bookkeeping,
            # is the DEFECT it exists to stop — and `drop` fails on a concurrent
            # worktree's held stash reflog lock, which is a supported configuration.
            print(
                f"the diff review restored the dirty tree but could not drop {entry} —"
                f" find it with `git stash list --format='%gd %H' | grep {entry}`"
                " and `git stash drop` that selector",
                file=stderr,
            )
    # Each half is capped ON ITS OWN and close.py's refusal goes LAST: one budget over
    # the pair spends it all on a megabyte reviewer log and drops the refusal entirely.
    captured = refusal.getvalue().strip()[-REVIEW_REFUSAL_TAIL:]
    if rc:
        log_id = (
            f"{story_id}-reviewer"
            if story_id.startswith("story-") and story_id.removeprefix("story-").isdigit()
            else "story-reviewer-review"
        )
        log = data_root() / "logs" / f"{log_id}.log"
        if log.is_file():
            from log_rotate import tail as log_tail

            tail = log_tail(log, REVIEW_REFUSAL_TAIL).strip()
            captured = f"{tail}\n{captured}".strip() if tail else captured
    return rc, state, captured


def finish_story(tree: Path, story_id: str, stop, stage_line, held) -> int:
    from close import leg
    from handback import tree_state
    from handoff import mark_handoff, mark_stage
    from overlap import unresolved_blocking
    from work import data_root

    rc, state, refusal = review_story(tree, story_id)
    if rc:
        cause = refusal or "the diff review produced no readable refusal; inspect its log"
        return stop(f"the diff review leg refused (rc {rc}): {cause}", rc)
    mark_stage(data_root(), story_id, "reviewer", "ran")
    if unresolved_blocking(state):
        why = "diff review recorded blocking findings; resume with a fresh executor to fix them"
        return stop(why, 0)
    free_slug = leg(story_id)[1]
    instruction = "run `/free-close` from that worktree" if free_slug else "run `/story-close`"
    print(stage_line())
    print(
        f"{story_id} produced commit {tree_state(tree)[0]} at {tree}. Read it, then {instruction}."
    )
    mark_handoff(data_root(), story_id, True)
    held.close()
    return rc
