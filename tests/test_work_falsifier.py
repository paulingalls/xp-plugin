"""Pytest falsifiers select exact node IDs, never names via ``-k``."""

import sys

from test_work import run


def pytest_k(tmp_path, expression, flag="-k ", runner=None):
    # `runner` is what the guard reads, so it is a single knob: a second parameter
    # overriding it would let a runner-spelling case silently test the default one.
    test_file = tmp_path / "test_selection.py"
    test_file.write_text("def test_selected():\n    pass\n")
    runner = runner or f"{sys.executable} -m pytest"
    return f"{runner} -q {test_file} {flag}{expression}"


def assert_node_id_refusal(result):
    assert result.returncode == 2
    assert "-k" in result.stderr
    assert "path/to/test.py::TestClass::test_name" in result.stderr


def test_bug_with_unmatched_pytest_k_is_refused_before_filing(tmp_path):
    result = run(
        [
            "bug",
            "--claim",
            "x",
            "--falsifier",
            pytest_k(tmp_path, "absent", runner="pytest"),
            "--files",
            "a",
        ],
        tmp_path,
    )
    assert_node_id_refusal(result)
    assert not (tmp_path / "work.md").exists()


def test_debt_with_matching_pytest_k_is_refused_before_filing(tmp_path):
    result = run(
        ["debt", "--claim", "x", "--falsifier", pytest_k(tmp_path, "selected"), "--files", "a"],
        tmp_path,
    )
    assert_node_id_refusal(result)
    assert not (tmp_path / "work.md").exists()


def test_pytest_k_attached_or_clustered_is_refused(tmp_path):
    for flag in ("-k", "-k=", "-xk ", "-vxk", "-dk "):
        falsifier = pytest_k(tmp_path, "selected", flag=flag)
        result = run(["debt", "--claim", "x", "--falsifier", falsifier, "--files", "a"], tmp_path)
        assert_node_id_refusal(result)
        assert not (tmp_path / "work.md").exists()


def test_resolution_with_pytest_k_is_refused_before_append(tmp_path):
    run(["bug", "--claim", "x", "--falsifier", "false", "--files", "a"], tmp_path, True)
    ref = run(["list"], tmp_path, True).stdout.split()[0]
    before = (tmp_path / "work.md").read_text()
    result = run(["resolve", "--ref", ref, "--falsifier", pytest_k(tmp_path, "selected")], tmp_path)
    assert_node_id_refusal(result)
    assert (tmp_path / "work.md").read_text() == before


def test_the_py_test_alias_is_refused_too(tmp_path):
    """pytest still installs `py.test`, so a guard that knows only one of the two
    names lets the whole rule be spelled around."""
    falsifier = pytest_k(tmp_path, "selected", runner="py.test")
    assert_node_id_refusal(
        run(["debt", "--claim", "x", "--falsifier", falsifier, "--files", "a"], tmp_path)
    )
    assert not (tmp_path / "work.md").exists()


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
