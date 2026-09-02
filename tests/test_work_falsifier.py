"""Repository falsifier rules and shipped record behavior."""

import os
import subprocess
import sys
from pathlib import Path

import pytest
from sprint_helpers import CONFIG, make_repo, work
from test_work import run
from work import entry_id

CHECKER = Path(__file__).parent / "scripts" / "check_falsifier_node_ids.py"
LEFTHOOK = Path(__file__).parent.parent / "lefthook.yml"


def check_records(root, text):
    (root / "work.md").write_text(text)
    return subprocess.run([sys.executable, CHECKER, root], capture_output=True, text=True)


def record(command, replacement=None):
    original = (
        "## debt 2026-08-29T00:00:00Z\n"
        "Claim: selected by name\n"
        f"Falsifier: `{command}`\n"
        "Files: tests/test_example.py\n\n"
    )
    if replacement is None:
        return original
    return (
        original
        + f"## resolved 2026-08-29T00:00:01Z\nResolves: {entry_id(original)}\n"
        + f"Falsifier: `{replacement}`\n\n"
    )


@pytest.mark.parametrize(
    "command",
    (
        "pytest -q tests/test_example.py -k selected",
        "pytest -q tests/test_example.py -kselected",
        "pytest -q tests/test_example.py -vxk selected",
        "py.test -q tests/test_example.py -k selected",
        f"{sys.executable} -m pytest -q tests/test_example.py -k selected",
    ),
)
def test_repo_checker_refuses_an_open_broad_test_selector(tmp_path, command):
    result = check_records(tmp_path, record(command))
    assert result.returncode == 1
    assert "exact node id" in result.stderr.lower()


def test_repo_checker_ignores_the_selector_on_a_resolved_record(tmp_path):
    text = record("pytest -q tests/test_example.py -k selected", replacement="true")
    assert check_records(tmp_path, text).returncode == 0


def test_repo_checker_refuses_a_resolution_that_selects_by_name(tmp_path):
    """Constraint 11 binds the replacement too, and the corpus substitutes it for the
    original — so the clean-resolution case alone would pass a checker that never
    read a resolution at all."""
    text = record("true", replacement="pytest -q tests/test_example.py -k selected")
    result = check_records(tmp_path, text)
    assert result.returncode == 1
    assert "exact node id" in result.stderr.lower()


@pytest.mark.parametrize(
    "command",
    (
        # A REAL node id, not a placeholder: since 2026-09-02 the checker verifies
        # that an exact id still resolves, so a fictional one is now correctly
        # refused and would assert the opposite of this test's name.
        "pytest -q tests/test_work.py::TestNote",
        f"{sys.executable} -c 'pass' -k",
    ),
)
def test_repo_checker_accepts_exact_or_non_test_commands(tmp_path, command):
    assert check_records(tmp_path, record(command)).returncode == 0


def test_repo_checker_refuses_an_exact_id_that_no_longer_resolves(tmp_path):
    """The other half of the rule above, and the one that was missing: naming an
    exact id buys nothing if nothing checks it. Measured at Sprint 16's close — a
    test moved file, its record kept the old path, pytest exited 5 on no match,
    and the release aborted on a defect that had not returned."""
    gone = "pytest -q tests/test_work_falsifier.py::test_that_moved_away"

    result = check_records(tmp_path, record(gone))

    assert result.returncode == 1, result.stdout
    assert "no longer collects" in result.stderr, result.stderr


def test_repo_checker_reports_when_there_is_no_record_file(tmp_path):
    result = subprocess.run([sys.executable, CHECKER, tmp_path], capture_output=True, text=True)
    assert result.returncode == 0
    assert "scanned nothing" in result.stdout


@pytest.mark.parametrize("argv", (["--help"], ["."]))
def test_repo_checker_needs_no_ambient_data_root_when_told_where_to_look(tmp_path, argv):
    """`data_root()` shells out to git and exits 2 outside a repo, so resolving it as an
    argparse default would make --help refuse and would tie an explicit root to the cwd."""
    env = {k: v for k, v in os.environ.items() if k != "XP_DATA"}
    result = subprocess.run(
        [sys.executable, CHECKER, *argv], capture_output=True, text=True, cwd=tmp_path, env=env
    )
    assert result.returncode == 0, result.stderr


def test_repo_pre_push_runs_the_falsifier_checker():
    pre_push = LEFTHOOK.read_text().split("pre-push:", 1)[1]
    assert "python3 tests/scripts/check_falsifier_node_ids.py" in pre_push


def test_non_pytest_falsifier_with_k_is_untouched(tmp_path):
    command = f"{sys.executable} -c 'pass' -k"
    result = run(["debt", "--claim", "x", "--falsifier", command, "--files", "a"], tmp_path)
    assert result.returncode == 0, result.stderr


def test_missing_node_id_is_left_to_pytest_exit_status(tmp_path):
    test_file = tmp_path / "test_selection.py"
    test_file.write_text("def test_present():\n    pass\n")
    command = f"{sys.executable} -m pytest -q {test_file}::test_absent"
    result = run(["bug", "--claim", "x", "--falsifier", command, "--files", "a"], tmp_path)
    assert result.returncode == 0, result.stderr


def test_unbalanced_shell_quote_retains_current_polarity_behavior(tmp_path):
    result = run(["bug", "--claim", "x", "--falsifier", "printf '", "--files", "a"], tmp_path)
    assert result.returncode == 0, result.stderr
    assert "Traceback" not in result.stderr


def test_an_unknown_coverage_tier_is_refused_with_the_available_names(tmp_path):
    config = CONFIG.replace("tests:\n", "tests:\n  fast: true\n")
    repo, env, _g = make_repo(tmp_path, config=config)
    result = work(
        repo,
        env,
        "debt",
        "--claim",
        "x",
        "--falsifier",
        "true",
        "--files",
        "a",
        "--covered-by",
        "missing",
    )
    assert result.returncode == 2
    assert "missing" in result.stderr and all(t in result.stderr for t in ("fast", "full"))
    assert not (tmp_path / "data" / "work.md").exists()


@pytest.mark.parametrize("field", ("claim", "files"))
def test_free_text_cannot_forge_a_coverage_declaration(tmp_path, field):
    repo, env, _g = make_repo(tmp_path)
    values = {"claim": "real", "files": "a.py"}
    values[field] += "\nCovered by: full"
    result = work(
        repo,
        env,
        "debt",
        "--claim",
        values["claim"],
        "--falsifier",
        "true",
        "--files",
        values["files"],
    )
    assert result.returncode == 0, result.stderr
    text = (tmp_path / "data" / "work.md").read_text()
    assert not [line for line in text.splitlines() if line.startswith("Covered by:")]
