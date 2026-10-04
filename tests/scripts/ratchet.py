#!/usr/bin/env python3
"""The size wall for this repo: shipped Python under the cap, tests under the ratio.

Usage: python3 tests/scripts/ratchet.py [--root PATH]
Exit 1 when either bound is crossed; the sprint hook runs it.
"""

import argparse
import sys
from pathlib import Path

SHIPPED_CAP = 4000
TEST_RATIO = 2.0


def count(paths) -> int:
    return sum(len(p.read_text().splitlines()) for p in paths)


def measure(root: Path) -> tuple[int, int]:
    shipped = count(p for p in (root / "plugins" / "xp-plugin").rglob("*.py"))
    tests = count(
        p for p in (root / "tests").rglob("*.py") if p.parent != root / "tests" / "scripts"
    )
    return shipped, tests


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=str(Path(__file__).resolve().parents[2]))
    root = Path(parser.parse_args().root)
    shipped, tests = measure(root)
    ratio = tests / shipped if shipped else 0.0
    print(f"shipped {shipped:>6}  cap {SHIPPED_CAP}")
    print(f"tests   {tests:>6}  ratio {ratio:.2f}  cap {TEST_RATIO:.1f}")
    over = []
    if shipped > SHIPPED_CAP:
        over.append(f"shipped Python is {shipped - SHIPPED_CAP} lines over the cap; delete")
    if ratio > TEST_RATIO:
        over.append(f"tests are {ratio:.2f}x shipped; delete tests an integration test covers")
    for line in over:
        print(f"refused: {line}", file=sys.stderr)
    return 1 if over else 0


if __name__ == "__main__":
    sys.exit(main())
