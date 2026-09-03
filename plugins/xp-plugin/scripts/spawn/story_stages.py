from pathlib import Path


def run_planner(story_id: str, card: str, tree: Path, handoff: str) -> tuple[int, str]:
    import review
    from handback import tree_state
    from handoff import draft_path
    from spawn import PLUGIN_ROOT, build_prompt, data_root, teammate_sections

    draft = draft_path(data_root(), story_id)
    before = draft.read_bytes() if draft.is_file() else None
    sections = teammate_sections(card, story_id, handoff, PLUGIN_ROOT)
    instruction = f"PLAN_PATH: {draft}\nWrite the plan, change no repo file, exit."
    sections.append(("Your stage", instruction))
    head = tree_state(tree)
    _result, error = review.run(build_prompt(sections), tree, name="planner", card=card)
    after = draft.read_bytes() if draft.is_file() else None
    if error:
        return 2, error
    if tree_state(tree) != head:
        return 2, "the planner changed the repository; it owns only the external plan"
    if not after or after == before or not after.strip():
        return 2, f"the planner did not write a new non-empty plan at {draft}"
    return 0, ""


def review_story(tree: Path, story_id: str) -> tuple[int, dict]:
    import contextlib
    import json

    from close import cmd_review, git, marker_path

    with contextlib.chdir(tree):
        # By SHA: refs/stash is one stack per clone, so a pop takes whoever pushed last.
        dirty = bool(git("status", "--porcelain").stdout.strip())
        if dirty and git("stash", "push", "-qu", "-m", story_id, check=False).returncode:
            return 2, {}
        entry = git("rev-parse", "-q", "--verify", "stash@{0}", check=False).stdout.strip()
        try:
            rc = cmd_review(story_id)
            state = json.loads(marker_path(story_id).read_text()) if not rc else {}
        finally:
            restored = git("stash", "apply", "-q", entry, check=False) if dirty else None
    return (2, {}) if restored and restored.returncode else (rc, state)
