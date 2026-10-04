"""Collection and mutation pressure for the slow registry contract."""

import ast
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.meta

ROOT = Path(__file__).resolve().parents[1]
STALE = ["tests/test_a.py::test_missing", "tests/test_b.py::test_gone"]
IDS = ["tests/test_a.py::test_fast", "tests/test_a.py::test_other", "tests/test_b.py::test_slow"]


def mutate(source, mode):
    tree = ast.parse(source)
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef):
            continue
        if node.name == "_validate_slow_registry" and mode == "disabled":
            node.body = [ast.Pass()]
        if node.name == "_slow_ids" and mode == "shard-count":
            for branch in ast.walk(node):
                if isinstance(branch, ast.If) and isinstance(branch.test, ast.Compare):
                    branch.test = ast.Constant(False)
        if node.name == "_full_suite_selected" and mode in ("always", "never"):
            node.body = [ast.Return(ast.Constant(mode == "always"))]
        if node.name == "pytest_collection_modifyitems":
            if mode == "late":
                node.decorator_list = (
                    ast.parse("@pytest.hookimpl(trylast=True)\ndef hook(): pass")
                    .body[0]
                    .decorator_list
                )
            if mode == "unmarked":
                node.body = [stmt for stmt in node.body if not isinstance(stmt, ast.For)]
    return ast.unparse(ast.fix_missing_locations(tree))


@pytest.fixture
def suite(tmp_path):
    root = tmp_path / "project"
    tests = root / "tests"
    tests.mkdir(parents=True)
    (root / "pytest.ini").write_text("[pytest]\ntestpaths = tests\nmarkers =\n slow: measured\n")
    source = (ROOT / "tests/conftest.py").read_text()
    if mode := os.environ.get("SLOW_REGISTRY_MUTATION"):
        source = mutate(source, mode)
    (tests / "conftest.py").write_text(source)
    for filename, names in [("a", ["fast", "other"]), ("b", ["slow"])]:
        (tests / f"test_{filename}.py").write_text(
            "from pathlib import Path\n"
            + "\n".join(
                f"def test_{name}():\n    Path({str(root / name)!r}).touch()\n" for name in names
            )
        )
    (tests / "__init__.py").touch()
    return root


def run(root, *args, ids=IDS, cwd=None, shards=False):
    registry = {"ids": ids}
    if shards:
        registry = {"shards": ["slow_tests-1.json", "slow_tests-2.json"], "count": len(ids)}
        for number, subset in enumerate((ids[:1], ids[1:]), 1):
            (root / f"tests/slow_tests-{number}.json").write_text(json.dumps(subset))
    (root / "tests/slow_tests.json").write_text(json.dumps(registry))
    for name in ("fast", "other", "slow"):
        (root / name).unlink(missing_ok=True)
    env = os.environ.copy()
    env.pop("PYTEST_XDIST_WORKER", None)
    env.pop("PYTEST_XDIST_WORKER_COUNT", None)
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", *args],
        cwd=cwd or root,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    bodies = {name for name in ("fast", "other", "slow") if (root / name).exists()}
    return result, bodies


def accepted(result, bodies, expected):
    assert result.returncode == 0, result.stdout + result.stderr
    assert bodies == set(expected), result.stdout + result.stderr


def refused(result, bodies):
    assert result.returncode != 0, f"bodies ran: {sorted(bodies)}\n{result.stdout}"
    assert all(node in result.stdout + result.stderr for node in STALE), (
        result.stdout + result.stderr
    )
    assert not bodies, f"bodies ran: {sorted(bodies)}"


@pytest.mark.parametrize("workers", [[], ["-n", "2"]])
@pytest.mark.parametrize(
    "selection,marker",
    [([], []), (["tests"], ["-m", "not slow"]), (["tests"], ["-m", "slow"])],
)
def test_full_collection_refuses_stale_ids_before_bodies(suite, workers, selection, marker):
    args = workers + selection + marker
    expected = (
        ["fast", "other"]
        if marker == ["-m", "not slow"]
        else ["slow"]
        if marker
        else ["fast", "other", "slow"]
    )
    accepted(*run(suite, *args, ids=[IDS[2]]), expected)
    refused(*run(suite, *args, ids=[IDS[2], *STALE]))


@pytest.mark.parametrize("filter_args", [["-k", "fast"], ["--deselect", IDS[2]]])
@pytest.mark.parametrize("selection", [[], ["tests"]])
def test_full_selection_checks_before_deselection(suite, filter_args, selection):
    expected = ["fast"] if filter_args[0] == "-k" else ["fast", "other"]
    accepted(*run(suite, *selection, *filter_args), expected)
    refused(*run(suite, *selection, *filter_args, ids=[*IDS, *STALE]))


@pytest.mark.parametrize("workers", [[], ["-n", "2"]])
@pytest.mark.parametrize(
    "selection,expected",
    [
        (["tests/test_a.py"], ["fast", "other"]),
        ([IDS[0]], ["fast"]),
    ],
)
def test_partial_selection_allows_unselected_registry_ids(suite, workers, selection, expected):
    accepted(*run(suite, *workers, *selection), expected)


@pytest.mark.parametrize(
    "restriction",
    [
        ["--ignore", "tests/test_b.py"],
        ["--ignore-glob", "*test_b.py"],
        ["--pyargs", "tests.test_a"],
    ],
)
def test_explicit_collection_restrictions_are_partial(suite, restriction):
    accepted(*run(suite, *restriction), ["fast", "other"])


def test_last_failed_collection_is_partial(suite):
    source = suite / "tests/test_a.py"
    original = source.read_text()
    source.write_text(original.replace("def test_fast():", "def test_fast():\n    assert False"))
    result, _ = run(suite)
    assert result.returncode == 1, result.stdout + result.stderr
    source.write_text(original)
    accepted(*run(suite, "--lf"), ["fast"])


@pytest.mark.parametrize(
    "spelling", ["root", "tests", "absolute_root", "absolute_tests", "alternate"]
)
def test_full_selection_path_spellings(suite, spelling):
    paths = {
        "root": ".",
        "tests": "tests",
        "absolute_root": str(suite),
        "absolute_tests": str(suite / "tests"),
        "alternate": "../project/tests",
    }
    cwd = suite
    if spelling == "alternate":
        cwd = suite.parent / "invocation"
        cwd.mkdir()
    accepted(*run(suite, paths[spelling], cwd=cwd), ["fast", "other", "slow"])
    refused(*run(suite, paths[spelling], ids=[*IDS, *STALE], cwd=cwd))


@pytest.mark.parametrize(
    "mode,node",
    [
        ("disabled", "test_full_collection_refuses_stale_ids_before_bodies"),
        ("never", "test_full_collection_refuses_stale_ids_before_bodies"),
        ("always", "test_partial_selection_allows_unselected_registry_ids"),
        ("always", "test_last_failed_collection_is_partial"),
        ("unmarked", "test_full_collection_refuses_stale_ids_before_bodies"),
        ("late", "test_full_selection_checks_before_deselection"),
        ("shard-count", "test_broken_shard_refuses_before_bodies"),
    ],
)
def test_diagnostics_reject_guard_mutations(mode, node):
    env = dict(os.environ, SLOW_REGISTRY_MUTATION=mode)
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", f"{__file__}::{node}"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert result.returncode == 1, result.stdout + result.stderr
    if mode in ("disabled", "never"):
        assert "bodies ran:" in result.stdout, result.stdout


def test_sharded_registry_preserves_selection_and_refusal(suite):
    accepted(*run(suite, "-m", "slow", ids=[IDS[2]], shards=True), ["slow"])
    refused(*run(suite, ids=[IDS[2], *STALE], shards=True))
    accepted(*run(suite, IDS[0], ids=[IDS[2], *STALE], shards=True), ["fast"])


@pytest.mark.parametrize("damage", ["missing", "unreadable", "omitted"])
def test_broken_shard_refuses_before_bodies(suite, damage):
    accepted(*run(suite, shards=True), ["fast", "other", "slow"])
    shard = suite / "tests/slow_tests-2.json"
    if damage == "missing":
        shard.unlink()
    elif damage == "unreadable":
        shard.write_text("unreadable JSON")
    else:
        registry = suite / "tests/slow_tests.json"
        manifest = json.loads(registry.read_text())
        manifest["shards"].pop()
        registry.write_text(json.dumps(manifest))
    for name in ("fast", "other", "slow"):
        (suite / name).unlink(missing_ok=True)
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q"], cwd=suite, capture_output=True, text=True
    )
    assert result.returncode != 0, result.stdout + result.stderr
    assert "slow registry" in result.stdout + result.stderr
    assert not any((suite / name).exists() for name in ("fast", "other", "slow"))


def test_registry_writer_emits_bounded_shards(tmp_path, monkeypatch):
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "regen", ROOT / "tests/scripts/regen_slow_tests.py"
    )
    regen = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(regen)
    registry = tmp_path / "slow_tests.json"
    registry.write_text(json.dumps({"_why": "measured", "threshold_seconds": 0.5}))
    monkeypatch.setattr(regen, "OUT", registry)
    census = tmp_path / "census"
    ids = [f"tests/test_a.py::test_{i:04}" for i in range(801)]
    census.write_text("\n".join(f"1.00s call {node}" for node in ids))
    assert regen.main([str(census)]) == 0
    manifest = json.loads(registry.read_text())
    assert manifest["count"] == len(ids)
    shards = [json.loads((tmp_path / name).read_text()) for name in manifest.get("shards", [])]
    assert shards and all(len(shard) <= 400 for shard in shards)
    assert [node for shard in shards for node in shard] == ids
