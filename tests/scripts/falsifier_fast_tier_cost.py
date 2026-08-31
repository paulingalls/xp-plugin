#!/usr/bin/env python3
"""Falsifier for the fast-tier cost debt (records 15aec3fc, 2b5a456d, 8fde7e83,
which share this one script). Two arms, and they guard different things.

THE RATCHET is the fixture arm: one session-scoped template repo copied per test
against the six git invocations it replaced. That comparison is CONSTRUCTED and
its effect is huge and stable — the lead measured 13.5x over 25 iterations, a
revert to the git build measures 1.0x — so no ambient load closes the gap. The
bound lives with the assertion, in tests/test_repo_templates.py (MIN_SPEEDUP).

THE SUITE BOUNDS BELOW ARE NOT THE RATCHET and must not be read as one. They are
the unusability guard the debt actually asked for: 'a commit gate slow enough
that someone stops running it, which is how --no-verify becomes tempting'. They
have moved once already (04f4a71e, total-only -> both, after a total-only bound
fired on healthy growth of 258 -> 691 tests at flat per-test cost). DO NOT MOVE
THEM AGAIN, in EITHER direction: raising them to make a red pass is the move the
debt forbids, and tightening them to prove a speed-up makes a load detector —
the populations are ~16% apart and this box's own measurement noise is ~10%.
Measure what a story CHANGED, in an arm of its own, as the fixture arm does.
DELETING THEM WAS TRIED AT THE v0.9.0 RELEASE AND REVERTED at that sprint's
review: the 129.13s red that motivated it was two gates sharing -n auto, and
re-measured alone this tree runs 84.4s / 873 tests = 97ms each. A deletion is
the widest possible raise, and it left three live records (the ones above)
certifying a wall-clock claim with a check that never starts a clock.
The dogfood fast tier caps xdist at eight workers: measured on this 16-core box,
auto took 135-253s while eight ran 934 tests in 98s under the same load.

The five-build git fixture is also the same-run load control. Wall clock alone
measured 137-242s on this tree while unrelated simulator and build work moved
host load from 16 to 320. Normalize only when that control is slower than its
measured 200ms reference; a suite-only regression leaves the control unchanged
and still reds, while a faster host never tightens either declared bound.
"""

import re
import subprocess
import sys
import time

MAX_SECONDS = 120
MAX_SECONDS_PER_TEST = 0.15
REFERENCE_GIT_MS = 200
MAX_LOAD_FACTOR = 2.0
FIXTURE_NODE = "tests/test_repo_templates.py::test_finished_fixture_copy_cost_against_git_build"
FIXTURE_PATTERN = re.compile(r"fixture cost ([0-9.]+)ms copy / ([0-9.]+)ms git = ([0-9.]+)x")


def fixture_cost_is_bounded() -> tuple[bool, float]:
    result = subprocess.run(
        ["pytest", "-q", "-s", FIXTURE_NODE],
        capture_output=True,
        text=True,
    )
    match = FIXTURE_PATTERN.search(result.stdout)
    if result.returncode or not match:
        sys.stdout.write(result.stdout)
        sys.stderr.write(result.stderr)
        return False, 0
    copy_ms, git_ms, speedup = (float(value) for value in match.groups())
    print(f"fixture cost {copy_ms:.2f}ms copy / {git_ms:.2f}ms git = {speedup:.2f}x")
    return True, git_ms


def suite_cost_is_bounded(elapsed: float, count: int, git_ms: float, after_ms: float) -> bool:
    load_factor = min(MAX_LOAD_FACTOR, max(1.0, min(git_ms, after_ms) / REFERENCE_GIT_MS))
    normalized = elapsed / load_factor
    per_test = normalized / count if count else float("inf")
    print(
        f"fast tier {elapsed:.1f}s raw / {normalized:.1f}s normalized / {count} tests"
        f" = {per_test * 1000:.0f}ms each"
    )
    return bool(count and normalized <= MAX_SECONDS and per_test <= MAX_SECONDS_PER_TEST)


def main() -> int:
    fixture_ok, git_ms = fixture_cost_is_bounded()
    if not fixture_ok:
        return 1
    started = time.monotonic()
    result = subprocess.run(
        ["pytest", "-q", "-n", "8", "-m", "not slow"],
        capture_output=True,
        text=True,
    )
    elapsed = time.monotonic() - started
    after_ok, after_ms = fixture_cost_is_bounded()
    match = re.search(r"(\d+) passed", result.stdout)
    count = int(match.group(1)) if match else 0
    if result.returncode or not count or not after_ok:
        sys.stdout.write(result.stdout)
        sys.stderr.write(result.stderr)
        return 1
    return int(not suite_cost_is_bounded(elapsed, count, git_ms, after_ms))


if __name__ == "__main__":
    raise SystemExit(main())
