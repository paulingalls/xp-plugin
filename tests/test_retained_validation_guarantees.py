"""Constructed regression fixtures promoted from resolved standalone falsifiers."""

import json
import subprocess
import sys
from pathlib import Path

from review_report import LIST_CAP, read_report


def test_findings_past_display_cap_reach_the_consumer_intact(tmp_path):
    findings = [f"finding {index}" for index in range(LIST_CAP + 5)]
    path = tmp_path / "report.json"
    path.write_text(
        json.dumps({"schema": 2, "fixed": [], "dropped": [], "debt": [], "blocking": findings})
    )
    report, error = read_report(path)
    assert not error
    assert report["blocking"] == findings


def test_constraint_references_mean_the_same_rule_in_a_scaffolded_consumer():
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, str(root / "tests/scripts/falsifier_constraint_citations_resolve.py")],
        cwd=root,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_hook_git_environment_cannot_redirect_fixture_reads(tmp_path):
    import os

    roots = [tmp_path / name for name in ("fixture", "foreign")]
    for root in roots:
        subprocess.run(["git", "init", "-q", str(root)], check=True)
    suite = Path(__file__).resolve().parent
    code = (
        "import runpy, subprocess, sys; "
        "sys.path.insert(0, sys.argv[1]); "
        "runpy.run_path(sys.argv[1] + '/conftest.py'); "
        "r = subprocess.run(['git', 'rev-parse', '--show-toplevel'], "
        "capture_output=True, text=True); print(r.stdout, end=''); exit(r.returncode)"
    )
    env = os.environ | {
        "GIT_DIR": str(roots[1] / ".git"),
        "GIT_WORK_TREE": str(roots[1]),
        "GIT_COMMON_DIR": str(roots[1] / ".git"),
        "GIT_INDEX_FILE": str(roots[1] / ".git/index"),
    }
    result = subprocess.run(
        [sys.executable, "-c", code, str(suite)],
        cwd=roots[0],
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert Path(result.stdout.strip()).resolve() == roots[0].resolve()
