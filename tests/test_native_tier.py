"""Selection policy executes sentinels and only collects installed-agent walks."""

import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from work import config_block_value

pytestmark = pytest.mark.meta
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "plugins/xp-plugin/scripts/close"))
import tier_legs  # noqa: E402

LIVE = {
    f"tests/test_sprint_planning_flow.py::test_planning_instructions_walk_actual_harness[{case}]"
    for case in ("claude-sonnet", "codex-gpt-6.1-sol")
}
ORDINARY = {"fast", "slow", "meta"}
NATIVE = {"native", "native_slow", "native_meta"}
EXPECTED = {
    "fast": {"fast"},
    "story": {"fast"},
    "full": ORDINARY,
    "leg-fast": {"fast"},
    "leg-slow": {"slow"},
    "leg-meta": {"meta"},
}


def environment():
    env = os.environ.copy()
    for key in ("PYTEST_ADDOPTS", "PYTEST_XDIST_WORKER", "PYTEST_XDIST_WORKER_COUNT"):
        env.pop(key, None)
    return env


def run(root, command, env=None):
    result = subprocess.run(
        command,
        shell=True,
        cwd=root,
        env=env or environment(),
        capture_output=True,
        text=True,
        timeout=300,
    )
    return result


def successful(result):
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.fixture
def policy(tmp_path, monkeypatch):
    root = tmp_path / "policy"
    (root / ".xp").mkdir(parents=True)
    source = (ROOT / ".xp/config.yml").read_text()
    ini = (ROOT / "pytest.ini").read_text()
    mode = os.environ.get("NATIVE_TIER_MUTATION", "")
    if mode == "default":
        ini = "\n".join(line for line in ini.splitlines() if not line.startswith("addopts"))
    monkeypatch.chdir(ROOT)
    commands = dict(config_block_value("tests"))
    legs = config_block_value("full_legs")
    commands["full"] = tier_legs.full_command(list(legs.items()))
    commands.update({f"leg-{k}": v for k, v in legs.items()})
    if mode.startswith("routine-"):
        key = mode.removeprefix("routine-")
        commands[key] = commands[key].replace(" and not native", "")
    if mode == "native":
        commands["native"] = commands["native"].replace("-m native", '-m "not native"')
    if mode == "full-native":
        source = source.replace('"not slow and not meta and not native"', '"not slow and not meta"')
    (root / ".xp/config.yml").write_text(source)
    (root / "pytest.ini").write_text(ini)
    tests = root / "tests"
    tests.mkdir()
    bodies = "from pathlib import Path\nimport pytest\n"
    for name in sorted(ORDINARY | NATIVE):
        marks = name.split("_") if name.startswith("native") else ([] if name == "fast" else [name])
        bodies += "".join(f"@pytest.mark.{mark}\n" for mark in marks)
        bodies += f"def test_{name}():\n    Path({str(root / name)!r}).touch()\n"
    (tests / "test_sentinels.py").write_text(bodies)
    return root, commands


def events(policy, command):
    root, _ = policy
    successful(run(root, command))
    return {name for name in ORDINARY | NATIVE if (root / name).exists()}


def test_default_excludes_native_bodies(policy):
    assert events(policy, "pytest -q") == ORDINARY


def test_native_tier_runs_only_native_bodies(policy):
    assert events(policy, policy[1]["native"]) == NATIVE


@pytest.mark.parametrize("tier", EXPECTED)
def test_routine_tiers_exclude_native_bodies(policy, tier):
    assert events(policy, policy[1][tier]) == EXPECTED[tier]


def collect(root, command):
    nodes = set()
    legs = (
        list(config_block_value("full_legs").values())
        if command == tier_legs.full_command(list(config_block_value("full_legs").items()))
        else command.split(" && ")
    )
    for leg in legs:
        result = run(root, shlex.join([*shlex.split(leg), "--collect-only"]))
        successful(result)
        nodes.update(
            line.strip()
            for line in result.stdout.splitlines()
            if line.startswith("tests/") and "::" in line
        )
    assert nodes, result.stdout + result.stderr
    return nodes


def test_actual_acceptance_collection(policy, tmp_path):
    root = ROOT
    mode = os.environ.get("NATIVE_TIER_MUTATION", "")
    if mode == "acceptance-marker":
        root = tmp_path / "collection"
        root.mkdir()
        for path in ROOT.iterdir():
            if path.name == "tests":
                shutil.copytree(
                    path, root / path.name, ignore=shutil.ignore_patterns("__pycache__")
                )
            else:
                (root / path.name).symlink_to(path, target_is_directory=path.is_dir())
        path = root / "tests/test_sprint_planning_flow.py"
        path.write_text(path.read_text().replace("@pytest.mark.native\n", ""))
    all_nodes = collect(root, 'pytest -q -m ""')
    slow = collect(root, "pytest -q -m slow")
    meta = collect(root, "pytest -q -m meta")
    ordinary = all_nodes - LIVE
    expected = {
        "default": ordinary,
        "full": ordinary,
        "fast": ordinary - slow - meta,
        "story": ordinary - slow - meta,
        "leg-fast": ordinary - slow - meta,
        "leg-slow": (ordinary & slow) - meta,
        "leg-meta": ordinary & meta,
        "native": LIVE,
    }
    commands = {"default": "pytest -q", **policy[1]}
    if mode == "ordinary-deselection":
        node = sorted(expected["fast"])[0]
        commands["fast"] += " --deselect " + shlex.quote(node)
    assert all_nodes >= LIVE
    for tier, command in commands.items():
        selected = collect(root, command)
        assert selected == expected[tier], (
            f"ordinary selection {tier}: missing={expected[tier] - selected}; "
            f"extra={selected - expected[tier]}"
        )


def test_full_legs_remain_routine(policy, monkeypatch):
    monkeypatch.chdir(policy[0])
    legs, refusal = tier_legs.declared()
    assert not refusal, refusal
    assert legs
    assert events(policy, tier_legs.full_command(legs)) == ORDINARY


MUTATIONS = [
    ("default", "test_default_excludes_native_bodies"),
    *[
        (f"routine-{tier}", f"test_routine_tiers_exclude_native_bodies[{tier}]")
        for tier in EXPECTED
    ],
    ("native", "test_native_tier_runs_only_native_bodies"),
    ("acceptance-marker", "test_actual_acceptance_collection"),
    ("ordinary-deselection", "test_actual_acceptance_collection"),
    ("full-native", "test_full_legs_remain_routine"),
]


@pytest.mark.parametrize("mode,node", MUTATIONS, ids=[mode for mode, _ in MUTATIONS])
def test_diagnostics_reject_policy_mutations(mode, node):
    env = environment() | {"NATIVE_TIER_MUTATION": mode}
    command = shlex.join(
        [sys.executable, "-m", "pytest", "-q", "-n", "4", f"tests/test_native_tier.py::{node}"]
    )
    result = run(ROOT, command, env)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "AssertionError" in result.stdout, result.stdout + result.stderr
    if mode == "ordinary-deselection":
        assert "ordinary selection fast" in result.stdout, result.stdout
