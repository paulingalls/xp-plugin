#!/usr/bin/env python3
"""XP process for coding agents: plan, review the plan, do, review the diff, land.

xp.py setup | session-start | recover
xp.py sprint plan|open|review|land|post-merge <id>
xp.py story <id> | story review <id> | story land <id>
xp.py free <slug> | free land <slug> | free post-merge <slug>
xp.py bug | debt | note | resolve ...
"""

import argparse
import importlib
import sys
from pathlib import Path

if sys.version_info < (3, 11):
    sys.exit(
        f"refused: xp.py needs Python 3.11+, found {sys.version.split()[0]}; use a newer python3"
    )
sys.path.insert(0, str(Path(__file__).resolve().parent))

STORY_ACTIONS = {"review": "cmd_story_review", "land": "cmd_story_land"}
FREE_ACTIONS = {"land": "cmd_free_land", "post-merge": "cmd_free_post_merge"}
SPRINT_ACTIONS = ("plan", "open", "review", "land", "post-merge")


def handler(module: str, name: str):
    def run(args) -> int:
        return getattr(importlib.import_module(f"xpcore.{module}"), name)(args)

    return run


def scoped(sub, name: str, actions: dict, spawn: str, help_text: str) -> None:
    p = sub.add_parser(name, help=help_text, description=help_text)
    p.add_argument("first", metavar="ACTION|ID", help=f"{' | '.join(actions)}, or the id")
    p.add_argument("id", nargs="?", help="the id, after an action")
    p.add_argument("--dry-run", action="store_true", help="print what would run")
    p.set_defaults(scope=name, actions=actions, spawn=spawn)


def build() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="xp.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = p.add_subparsers(dest="command", required=True, metavar="COMMAND")
    for name, module, fn, text in (
        ("setup", "setup", "cmd_setup", "scaffold .xp/ and the git hooks"),
        ("session-start", "session", "cmd_session_start", "SessionStart hook injection"),
        ("recover", "session", "cmd_recover", "print digest, open cards, open records"),
    ):
        sub.add_parser(name, help=text, description=text).set_defaults(run=handler(module, fn))

    sp = sub.add_parser("sprint", help="plan|open|review|land|post-merge a sprint")
    sp.add_argument("action", choices=SPRINT_ACTIONS)
    sp.add_argument("id", help="sprint id, e.g. 12")
    sp.add_argument("--dry-run", action="store_true", help="print what would run")
    sp.set_defaults(scope="sprint")
    scoped(
        sub, "story", STORY_ACTIONS, "cmd_story", "run a story's missing stages, review, or land"
    )
    scoped(sub, "free", FREE_ACTIONS, "cmd_free", "start, land, or tag a free patch")

    for name, text in (("bug", "file a bug (red falsifier)"), ("debt", "file debt (green)")):
        r = sub.add_parser(name, help=text, description=text)
        r.add_argument("--claim", required=True, help="what is wrong")
        r.add_argument("--falsifier", required=True, help="command whose polarity is checked")
        r.add_argument("--files", default="", help="comma-separated paths")
        if name == "debt":
            r.add_argument("--too-big", required=True, help="why it is too big to fix now")
            r.add_argument("--too-important", required=True, help="why dropping it is wrong")
        r.set_defaults(run=handler("records", f"cmd_{name}"))
    n = sub.add_parser("note", help="record a note", description="record a note")
    n.add_argument("text", nargs="+")
    n.set_defaults(run=handler("records", "cmd_note"))
    r = sub.add_parser("resolve", help="resolve a record with a green falsifier")
    r.add_argument("--ref", required=True, help="record id")
    r.add_argument("--falsifier", required=True, help="command that must now pass")
    r.set_defaults(run=handler("records", "cmd_resolve"))
    return p


def route(p: argparse.ArgumentParser, args) -> None:
    if args.command == "sprint":
        args.run = handler("sprint", f"cmd_sprint_{args.action.replace('-', '_')}")
    elif args.command in ("story", "free"):
        if args.first in args.actions:
            if not args.id:
                p.error(f"{args.command} {args.first} needs an id")
            module = "land" if args.first in ("land", "post-merge") else args.scope
            args.run = handler(module, args.actions[args.first])
        elif args.id:
            p.error(f"unknown {args.command} action {args.first!r}")
        else:
            args.id = args.first
            args.run = handler(args.scope, args.spawn)
    elif args.command == "note":
        args.text = " ".join(args.text)


def main(argv=None) -> int:
    p = build()
    args = p.parse_args(argv)
    route(p, args)
    from xpcore.gitx import GitError

    try:
        return args.run(args)
    except GitError as exc:
        print(f"failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
