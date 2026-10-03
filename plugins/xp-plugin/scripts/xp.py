#!/usr/bin/env python3
"""Open, review, integrate and release work through the existing lifecycle owners."""

import argparse
import os
import sys
from pathlib import Path

sys.path[:0] = [str(Path(__file__).parent), str(Path(__file__).parent / "close")]
from close import cmd_land, cmd_review, default_branch, fail, integration_target  # noqa: E402
from work import chdir_repo_root  # noqa: E402


def main(argv=None, *, legacy=False) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) >= 3 and argv[0] in ("story", "free") and argv[2] in ("repair", "salvage"):
        return fail(
            f"refused: {argv[0]} {argv[2]} is retired; inspect preserved work, then "
            f"explicitly run `xp.py {argv[0]} {argv[1]} review`; "
            "use `spawn.py resume <story-id>` when execution remains unfinished"
        )
    p = argparse.ArgumentParser(prog="xp.py", description=__doc__)
    sub = p.add_subparsers(dest="kind", required=True)
    sp = sub.add_parser("sprint")
    sp.add_argument("sprint_id")
    sp.add_argument(
        "action",
        choices=["open", "review", "salvage", "land", "post-merge", "milestone-done"]
        + (["start"] if legacy else []),
    )
    sp.add_argument("--dry-run", action="store_true")
    f = sub.add_parser("free")
    f.add_argument("slug")
    f.add_argument(
        "action", choices=["start", "review", "acknowledge-validation", "land", "post-merge"]
    )
    f.add_argument("--dry-run", action="store_true")
    f.add_argument("--reason", default="")
    s = sub.add_parser("story")
    s.add_argument("story_id")
    s.add_argument("action", choices=["review", "acknowledge-validation", "land"])
    # Derived: PR mode cannot integrate into a recorded sprint branch.
    s.add_argument("--merge-mode", choices=["pr", "local"], default=None)
    s.add_argument("--dry-run", action="store_true")
    s.add_argument("--reason", default="")
    a = p.parse_args(argv)
    if a.dry_run:
        os.environ["GIT_OPTIONAL_LOCKS"] = "0"
    # Unknown roles fail safe; this bounds the injected close path, not forged env.
    role = os.environ.get("XP_ROLE", "lead")
    if role != "lead":
        return fail(
            f"refused: XP_ROLE={role!r} — only the lead may run lifecycle actions. "
            "Hand back a green Verify; the lead owns the judgment gap and the merge"
        )
    if not chdir_repo_root():
        return fail("refused: not inside a git repository")
    if a.kind == "free":
        import free

        if a.action == "start":
            return free.cmd_start(a.slug, a.dry_run)
        if a.action == "review":
            return free.cmd_review(a.slug, a.dry_run)
        if a.action == "acknowledge-validation" and a.dry_run:
            return fail(
                "refused: validation disposition cannot be previewed; run without --dry-run"
            )
        if a.action == "acknowledge-validation":
            from review_validation import acknowledge

            key, _, error = free.current_free(a.slug)
            return fail(error) if error else acknowledge(key, a.reason)
        if a.action == "land":
            return free.cmd_land(a.slug, a.dry_run)
        return free.cmd_post_merge(a.slug, a.dry_run)
    if a.kind == "sprint":
        import sprint_close

        if a.action == "open":
            from open_sprint import cmd_open

            return cmd_open(a.sprint_id, a.dry_run)
        if a.action == "start":
            return sprint_close.cmd_start(a.sprint_id, a.dry_run)
        if a.action == "review":
            import sprint_review

            return sprint_review.cmd_review(a.sprint_id, a.dry_run)
        if a.action == "salvage":
            return sprint_close.cmd_salvage(a.sprint_id, a.dry_run)
        if a.action == "land":
            return sprint_close.cmd_land(a.sprint_id, a.dry_run)
        if a.action == "milestone-done":
            return sprint_close.milestone.cmd_done(a.sprint_id, a.dry_run)
        return sprint_close.cmd_post_merge(a.sprint_id, a.dry_run)
    if a.action == "review":
        return cmd_review(a.story_id, a.dry_run)
    if a.action == "acknowledge-validation" and a.dry_run:
        return fail("refused: validation disposition cannot be previewed; run without --dry-run")
    if a.action == "acknowledge-validation":
        from review_validation import acknowledge

        return acknowledge(a.story_id, a.reason)
    mode = a.merge_mode or ("local" if integration_target() != default_branch() else "pr")
    return cmd_land(a.story_id, mode, a.dry_run)


if __name__ == "__main__":
    sys.exit(main())
