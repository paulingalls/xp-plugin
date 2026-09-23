"""The suite's default data root is isolated across processes and xdist workers."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from env import data_root

ROOT = Path(__file__).parent.parent
MARKER = "XP_TEST_DATA_ROOT"


def real_data_root():
    saved = os.environ.pop("XP_DATA", None)
    try:
        return data_root()
    finally:
        if saved is not None:
            os.environ["XP_DATA"] = saved


def child_root(env):
    proc = subprocess.run(
        [sys.executable, "-c", "from env import data_root; print(data_root())"],
        cwd=ROOT,
        env=env | {"PYTHONPATH": str(ROOT / "plugins/xp-plugin/scripts")},
        capture_output=True,
        text=True,
        check=True,
    )
    return Path(proc.stdout.strip())


def test_inherited_data_root_is_guarded():
    guard = Path(os.environ[MARKER])
    assert guard.is_dir()
    assert Path(os.environ["XP_DATA"]) == guard
    assert not guard.is_relative_to(Path.home() / ".xp")
    assert data_root() == guard
    assert child_root(dict(os.environ)) == guard


def test_real_data_root_escapes_the_guard():
    guard = os.environ["XP_DATA"]
    assert real_data_root().parent == Path.home() / ".xp" / "data"
    assert os.environ["XP_DATA"] == guard


@pytest.mark.parametrize("probe", range(4))
def test_inner_probe(probe):
    results = os.environ.get("XP_GUARD_PROBE_RESULTS")
    if results is None:
        pytest.skip("runs only in the nested pytest")
    guard = Path(os.environ[MARKER])
    observed = data_root()
    child = child_root(dict(os.environ))
    worker = os.environ.get("PYTEST_XDIST_WORKER")
    (Path(results) / f"{probe}.json").write_text(
        json.dumps(
            {"guard": str(guard), "root": str(observed), "child": str(child), "worker": worker}
        )
    )
    assert guard == observed == child
    assert observed != Path(os.environ["XP_GUARD_POISON"])


@pytest.mark.parametrize("workers", [[], ["-n", "2"]], ids=["serial", "xdist"])
def test_exported_data_root_cannot_win(tmp_path, workers):
    poison = tmp_path / "exported"
    poison.mkdir()
    results = tmp_path / "results"
    results.mkdir()
    controller = tmp_path / "controller.json"
    (tmp_path / "xp_guard_controller_probe.py").write_text(
        "import json, os\n"
        "def pytest_sessionstart(session):\n"
        "    if 'PYTEST_XDIST_WORKER' not in os.environ:\n"
        "        with open(os.environ['XP_GUARD_CONTROLLER'], 'w') as out:\n"
        "            json.dump({'root': os.environ.get('XP_DATA'), "
        "'guard': os.environ.get('XP_TEST_DATA_ROOT')}, out)\n"
    )
    env = dict(os.environ)
    env.pop(MARKER, None)
    env.pop("PYTEST_XDIST_WORKER", None)
    env.update(
        XP_DATA=str(poison),
        XP_GUARD_POISON=str(poison),
        XP_GUARD_PROBE_RESULTS=str(results),
        XP_GUARD_CONTROLLER=str(controller),
        PYTHONPATH=str(tmp_path) + os.pathsep + env.get("PYTHONPATH", ""),
    )
    nodes = [f"tests/test_data_root_guard.py::test_inner_probe[{i}]" for i in range(4)]
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "xp_guard_controller_probe", *workers, *nodes],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    controller_env = json.loads(controller.read_text())
    assert controller_env["root"] == controller_env["guard"] != str(poison)
    found = [json.loads((results / f"{i}.json").read_text()) for i in range(4)]
    worker_ids = {item["worker"] for item in found}
    assert len(worker_ids) == (2 if workers else 1)
    if not workers:
        assert worker_ids == {None}
    assert len({item["guard"] for item in found}) == 1
    assert all(item["root"] == item["child"] == item["guard"] != str(poison) for item in found)


def test_explicit_data_root_wins(tmp_path, monkeypatch):
    custom = tmp_path / "custom"
    monkeypatch.setenv("XP_DATA", str(custom))
    assert data_root() == custom
    assert child_root(dict(os.environ)) == custom
    env = dict(os.environ) | {"XP_DATA": str(tmp_path / "child")}
    assert child_root(env) == tmp_path / "child"
