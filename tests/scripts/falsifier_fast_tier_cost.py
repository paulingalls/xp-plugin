#!/usr/bin/env python3
import re
import subprocess
import sys
import time

MAX_SECONDS = 120
MAX_SECONDS_PER_TEST = 0.15
MIN_FIXTURE_SPEEDUP = 5.0
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
    if speedup < MIN_FIXTURE_SPEEDUP:
        print(f"fixture copy must be at least {MIN_FIXTURE_SPEEDUP:.1f}x faster than git build")
        return False
    return True


def main() -> int:
    if not fixture_cost_is_bounded():
        return 1
    started = time.monotonic()
    result = subprocess.run(
        ["pytest", "-q", "-n", "auto", "-m", "not slow"],
        capture_output=True,
        text=True,
    )
    elapsed = time.monotonic() - started
    match = re.search(r"(\d+) passed", result.stdout)
    count = int(match.group(1)) if match else 0
    per_test = elapsed / count if count else float("inf")
    print(f"fast tier {elapsed:.1f}s / {count} tests = {per_test * 1000:.0f}ms each")
    if result.returncode or not count:
        sys.stdout.write(result.stdout)
        sys.stderr.write(result.stderr)
        return 1
    return int(elapsed > MAX_SECONDS or per_test > MAX_SECONDS_PER_TEST)


if __name__ == "__main__":
    raise SystemExit(main())
