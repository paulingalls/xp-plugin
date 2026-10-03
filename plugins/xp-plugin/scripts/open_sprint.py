#!/usr/bin/env python3
"""Open a sprint on its freshly cut branch without running close checks."""

import sys
from pathlib import Path

sys.path[:0] = [str(Path(__file__).parent / d) for d in ("", "close")]

import env  # noqa: E402


def cmd_open(sprint_id: str, dry_run: bool = False) -> int:
    import lifecycle as lc
    from close import config_flat, default_branch, fail, git
    from milestone import TERMINAL, find, move, sprint_stories
    from sprint_close import _running_slate_refusal, supersede_slate_marker
    from work import missing_plan_refusal, plan_path

    plan = plan_path()
    if not plan.exists():
        return fail(f"refused: {missing_plan_refusal()}")
    members = sprint_stories(plan.read_text(), sprint_id)
    if not members:
        return fail(f"refused: no `### Sprint {sprint_id}` section in {plan}")
    branch = git("branch", "--show-current").stdout.strip()
    if not branch or branch == default_branch():
        return fail("refused: open the sprint from its freshly cut branch, not trunk")
    if branch != (expected := env.sprint_branch_name(sprint_id)):
        return fail(f"refused: open sprint {sprint_id} from {expected}, not {branch}")
    recorded = env.sprint_branch()
    terminal = all(member.endswith(TERMINAL) for member in members)
    if recorded == branch:
        next_step = " Run `/sprint-close`" if terminal else ""
        return fail(f"refused: sprint {sprint_id} is already open.{next_step}")
    if recorded:
        return fail(
            f"refused: {env.sprint_branch_path()} records {recorded}, not {branch} — "
            "clear it only after that sprint lands"
        )
    if terminal:
        return fail(
            f"refused: sprint {sprint_id} has nothing to open — every story is done"
            " or retired. Run `/sprint-close`"
        )
    if running := _running_slate_refusal(sprint_id):
        return fail(running)
    if dry_run:
        print(f"dry run: {branch} opens sprint {sprint_id}; nothing ran, nothing recorded")
        return 0
    if red := lc.run(config_flat(lc.KEY), "sprint-open", sprint_id):
        return fail(red)
    if running := _running_slate_refusal(sprint_id):
        return fail(running)
    if error := supersede_slate_marker(sprint_id):
        return fail(error)
    env.record_sprint_branch(branch)
    if (owner := find(plan.read_text(), sprint_id)) and owner.status == "planned":
        move(sprint_id)
    print(f"sprint branch: {branch}\nsprint {sprint_id} opened; {len(members)} stories")
    return 0


def main() -> int:
    from xp import main as dispatch

    return dispatch(["sprint", *sys.argv[1:2], "open", *sys.argv[2:]])


if __name__ == "__main__":
    raise SystemExit(main())
