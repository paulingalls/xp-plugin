import runpy
from pathlib import Path

SCRIPT = Path(__file__).parent / "scripts" / "falsifier_fast_tier_cost.py"
MODULE = runpy.run_path(str(SCRIPT))
CAP = MODULE["MAX_SECONDS"]
PER_TEST = MODULE["MAX_SECONDS_PER_TEST"]


def bounded(elapsed, count, before_ms, after_ms):
    return MODULE["suite_cost_is_bounded"](elapsed, count, before_ms, after_ms)


def roomy(seconds):
    """A test count generous enough that the PER-TEST bound cannot be what reds.
    These two cases are about the TOTAL ceiling; sharing one count let the
    per-test bound answer for it, and the 2026-09-02 re-cut of MAX_SECONDS is
    what exposed that — both cases were written against a literal 120."""
    return int(seconds / PER_TEST * 2)


def test_a_slow_same_run_control_normalizes_host_contention():
    assert bounded(200, 1000, 400, 400)


def test_a_suite_only_slowdown_still_reds():
    assert not bounded(200, 1000, 200, 200)


def test_a_transient_slow_control_cannot_discount_the_later_suite():
    assert not bounded(200, 1000, 2000, 200)


def test_the_host_discount_has_an_upper_bound():
    """However slow the control, the discount caps at MAX_LOAD_FACTOR, so a suite
    past twice the ceiling still reds. Derived from CAP so a re-cut cannot quietly
    turn this into a case the discount now covers."""
    raw = 2 * CAP + 20
    assert not bounded(raw, roomy(raw), 10_000, 10_000)


def test_a_fast_host_does_not_tighten_the_declared_bounds():
    """A control faster than its reference never makes the ceiling stricter: the
    boundary sits at CAP wherever CAP is, asserted from both sides."""
    assert bounded(CAP - 1, roomy(CAP), 100, 100)
    assert not bounded(CAP + 1, roomy(CAP), 200, 200)
