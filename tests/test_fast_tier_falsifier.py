import runpy
from pathlib import Path

SCRIPT = Path(__file__).parent / "scripts" / "falsifier_fast_tier_cost.py"


def bounded(elapsed, count, git_ms):
    return runpy.run_path(str(SCRIPT))["suite_cost_is_bounded"](elapsed, count, git_ms)


def test_a_slow_same_run_control_normalizes_host_contention():
    assert bounded(200, 1000, 400)


def test_a_suite_only_slowdown_still_reds():
    assert not bounded(200, 1000, 200)


def test_a_fast_host_does_not_tighten_the_declared_bounds():
    assert bounded(119, 1000, 100)
    assert not bounded(121, 1000, 200)
