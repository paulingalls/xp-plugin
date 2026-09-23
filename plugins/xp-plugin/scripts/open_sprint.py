#!/usr/bin/env python3
"""Open a sprint on its freshly cut branch without running close checks."""

import argparse
import os
import sys
from pathlib import Path

sys.path[:0] = [str(Path(__file__).parent / d) for d in ("", "close")]

import env  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sprint_id", metavar="<id>")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    from close import default_branch, fail, git
    from milestone import TERMINAL, sprint_stories
    from sprint_close import cmd_start
    from work import chdir_repo_root, plan_path

    role = os.environ.get("XP_ROLE", "lead")
    if role != "lead":
        return fail(
            f"refused: XP_ROLE={role!r} — only the lead may open a sprint. You hand back"
            " a green Verify; the lead owns the sprint's branch and its merge"
        )
    if not chdir_repo_root():
        return fail("refused: not inside a git repository")

    plan = plan_path()
    if not plan.exists():
        return cmd_start(args.sprint_id, args.dry_run)
    members = sprint_stories(plan.read_text(), args.sprint_id)
    if not members:
        return cmd_start(args.sprint_id, args.dry_run)
    branch = git("branch", "--show-current").stdout.strip()
    if not branch or branch == default_branch() or branch != env.sprint_branch_name(args.sprint_id):
        return cmd_start(args.sprint_id, args.dry_run)

    recorded = env.sprint_branch()
    terminal = all(member.endswith(TERMINAL) for member in members)
    if not recorded and terminal:
        return fail(
            f"refused: sprint {args.sprint_id} has nothing to open — every story is done"
            " or retired. Run `/sprint-close`"
        )
    if recorded == branch:
        next_step = " Run `/sprint-close`" if terminal else ""
        return fail(f"refused: sprint {args.sprint_id} is already open.{next_step}")
    if recorded:  # another sprint's branch: this refuses and writes nothing
        env.record_sprint_branch(branch)
    return cmd_start(args.sprint_id, args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
