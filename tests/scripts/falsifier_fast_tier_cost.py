#!/usr/bin/env python3
"""Falsifier for the fast-tier cost debt (records 15aec3fc, 2b5a456d, 8fde7e83,
which share this one script).

THE RATCHET is the fixture arm: one session-scoped template repo copied per test
against the six git invocations it replaced. That comparison is CONSTRUCTED and
its effect is huge and stable — the lead measured 13.5x over 25 iterations, a
revert to the git build measures 1.0x — so no ambient load closes the gap. The
bound lives with the assertion, in tests/test_repo_templates.py (MIN_SPEEDUP).
"""

import re
import subprocess
import sys

FIXTURE_NODE = "tests/test_repo_templates.py::test_finished_fixture_copy_cost_against_git_build"
FIXTURE_PATTERN = re.compile(r"fixture cost ([0-9.]+)ms copy / ([0-9.]+)ms git = ([0-9.]+)x")


def fixture_cost_is_bounded() -> bool:
    result = subprocess.run(
        ["pytest", "-q", "-s", FIXTURE_NODE],
        capture_output=True,
        text=True,
    )
    match = FIXTURE_PATTERN.search(result.stdout)
    if result.returncode or not match:
        sys.stdout.write(result.stdout)
        sys.stderr.write(result.stderr)
        return False
    copy_ms, git_ms, speedup = (float(value) for value in match.groups())
    print(f"fixture cost {copy_ms:.2f}ms copy / {git_ms:.2f}ms git = {speedup:.2f}x")
    return True


def main() -> int:
    return int(not fixture_cost_is_bounded())


if __name__ == "__main__":
    raise SystemExit(main())
