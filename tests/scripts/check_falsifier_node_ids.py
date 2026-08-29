#!/usr/bin/env python3
"""Refuse this repository's open falsifiers that select tests by name."""

import argparse
import re
import shlex
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "plugins/xp-plugin/scripts"))

from env import data_root  # noqa: E402
from sprint_close import corpus  # noqa: E402


def selects_by_name(command: str) -> bool:
    try:
        words = shlex.split(command)
    except ValueError:
        return False
    selects = any(word.startswith("-k") or re.fullmatch(r"-[dflqsvx]+k.*", word) for word in words)
    return selects and any(Path(word).name in ("pytest", "py.test") for word in words)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    # A ROOT, not a work.md path, because corpus() reads root/work.md itself: a file
    # argument it ignored would report a clean scan of a file it never opened. Resolved
    # after parsing so --help needs neither a git repo nor XP_DATA.
    parser.add_argument("root", nargs="?", type=Path, help="data root holding work.md")
    args = parser.parse_args()
    root = args.root or data_root()
    work = root / "work.md"
    if not work.exists():
        print(f"scanned nothing: {work} is absent")
        return 0
    try:
        offenders = [
            (eid, command)
            for eid, _head, command, _covered in corpus(root)
            if selects_by_name(command)
        ]
    except OSError as exc:
        print(f"refused: cannot read {work}: {exc}", file=sys.stderr)
        return 2
    if offenders:
        refs = ", ".join(eid for eid, _command in offenders)
        print(
            f"refused: open falsifiers {refs} select tests by name; replace each broad"
            " selector with an exact node id",
            file=sys.stderr,
        )
        return 1
    print(f"checked open falsifiers in {work}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
