#!/usr/bin/env python3
"""Append bug/debt/note records to work.md. The only writer — see PROCESS.md.

A bug's falsifier must red (exit nonzero) right now; a debt's must be green.
The check runs at creation because that is the only cheap enforcement point;
semantic review of falsifiers belongs to the story reviewer.
"""

import argparse
import fcntl
import hashlib
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

NOTE_CAP = 2000  # chars; a judgment call, not a derived number


def neutralize(text: str) -> str:
    """A record body must not mint entry headers (Honesty: the record cannot lie)."""
    return text.replace("\n## ", "\n ## ")


def data_root() -> Path:
    if env := os.environ.get("XP_DATA"):
        return Path(env)
    proc = subprocess.run(["git", "rev-parse", "--git-common-dir"], capture_output=True, text=True)
    if proc.returncode != 0:
        print("not inside a git repository and XP_DATA is unset", file=sys.stderr)
        raise SystemExit(2)
    common = proc.stdout.strip()
    project_id = hashlib.sha256(os.path.realpath(common).encode()).hexdigest()[:12]
    return Path.home() / ".xp" / "data" / project_id


def append(root: Path, block: str) -> None:
    root.mkdir(parents=True, exist_ok=True)
    with open(root / "work.md", "a") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        f.write(block)


def falsifier_is_green(command: str) -> bool:
    return subprocess.run(command, shell=True, capture_output=True).returncode == 0


def entry(kind: str, args: argparse.Namespace) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return (
        f"## {kind} {ts}\n"
        f"Claim: {neutralize(args.claim)}\n"
        f"Falsifier: `{args.falsifier}`\n"
        f"Files: {args.files}\n\n"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="kind", required=True)
    for kind in ("bug", "debt"):
        p = sub.add_parser(kind)
        p.add_argument("--claim", required=True)
        p.add_argument("--falsifier", required=True, help="shell command; red = exit nonzero")
        p.add_argument("--files", required=True, help="comma-separated paths")
    sub.add_parser("note").add_argument("text")
    args = parser.parse_args()

    root = data_root()
    if args.kind == "note":
        text = args.text
        if len(text) > NOTE_CAP:
            dropped = len(text) - NOTE_CAP
            text = f"{text[:NOTE_CAP]} [truncated: {dropped} chars dropped]"
            print(f"note truncated: {dropped} chars over NOTE_CAP={NOTE_CAP}", file=sys.stderr)
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        append(root, f"## note {ts}\n{neutralize(text)}\n\n")
        return 0

    green = falsifier_is_green(args.falsifier)  # outside the lock: may be slow
    if args.kind == "bug" and green:
        print(
            f"refused: falsifier is green ({args.falsifier!r} exited 0) — a bug's"
            " falsifier must red now. File as debt if the claim is about the future.",
            file=sys.stderr,
        )
        return 2
    if args.kind == "debt" and not green:
        print(
            f"refused: falsifier already reds ({args.falsifier!r}) — file as bug and fix it now.",
            file=sys.stderr,
        )
        return 2
    append(root, entry(args.kind, args))
    return 0


if __name__ == "__main__":
    sys.exit(main())
