from pathlib import Path

REVIEW_REFUSAL_TAIL = 2000


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
        entry = git("rev-parse", "-q", "--verify", "stash@{0}", check=False).stdout.strip()
        try:
            with contextlib.redirect_stderr(refusal):
                rc = cmd_review(story_id)
            state = json.loads(marker_path(story_id).read_text()) if not rc else {}
        finally:
            restored = git("stash", "apply", "-q", entry, check=False) if dirty else None
    if restored and restored.returncode:
        return 2, {}, "the diff review could not restore the dirty tree"
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
            tail = log.read_text(errors="replace").strip()[-REVIEW_REFUSAL_TAIL:]
            captured = f"{tail}\n{captured}".strip() if tail else captured
    return rc, state, captured
