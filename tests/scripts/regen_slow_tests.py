#!/usr/bin/env python3
"""Regenerate tests/slow_tests.json from a duration census.

Run on a QUIET tree: this suite is subprocess-bound, and a contended census
marks whatever happened to be unlucky. Usage:

    pytest -q -n 8 --durations=0 > /tmp/census.txt
    python3 tests/scripts/regen_slow_tests.py /tmp/census.txt [threshold]

The census runs WITHOUT `-m "not slow"` on purpose — excluding the marked tests
would measure only what is already fast and could never demote a test back.
"""

import json
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "slow_tests.json"
ROW = re.compile(r"^(\d+\.\d+)s (?:call|setup|teardown)\s+(\S+)")


def totals(census: str) -> dict[str, float]:
    per: dict[str, float] = {}
    for line in census.splitlines():
        if m := ROW.match(line):
            per[m.group(2)] = per.get(m.group(2), 0.0) + float(m.group(1))
    return per


def main(argv: list[str]) -> int:
    if not argv:
        return print(__doc__) or 2
    per = totals(Path(argv[0]).read_text())
    if not per:
        print(f"refused: no `--durations` rows in {argv[0]} — run pytest with --durations=0")
        return 2
    prior = json.loads(OUT.read_text())
    threshold = float(argv[1]) if len(argv) > 1 else prior["threshold_seconds"]
    ids = sorted(n for n, v in per.items() if v >= threshold)
    sha = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True
    ).stdout.strip()
    OUT.write_text(
        json.dumps(
            {
                "_why": prior["_why"],
                "threshold_seconds": threshold,
                "measured_at": sha,
                "measured_on": date.today().isoformat(),
                "census": f"{len(per)} tests timed, {sum(per.values()):.0f}s CPU",
                "ids": ids,
            },
            indent=1,
        )
        + "\n"
    )
    print(f"{OUT}: {len(ids)} of {len(per)} tests at or above {threshold}s")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
