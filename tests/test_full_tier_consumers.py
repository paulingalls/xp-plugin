"""Walk full-tier consumers with measured events and release controls."""

import json
import shlex
import shutil
import subprocess
import sys

import pytest
from sprint_helpers import PLUGIN, marker_path, record_reviews, sprint
from test_setup import bare_repo
from test_sprint_tier_receipt import add_origin


def publishing(tmp_path, repo, env, g):
    add_origin(tmp_path, repo, env, g)
    (tmp_path / "data/closes.jsonl").write_text("")
    saved = json.loads(marker_path(tmp_path).read_text())
    saved["reviewed_head"] = g("rev-parse", "HEAD").stdout.strip()
    marker_path(tmp_path).write_text(json.dumps(saved))
    gh = tmp_path / "bin/gh"
    gh.write_text("#!/bin/sh\necho https://example.test/pr/1\n")
    gh.chmod(0o755)


def shell_full(repo, env, plugin=PLUGIN):
    python = repo.parent / "bin/python3"
    if not python.exists():
        python.symlink_to(sys.executable)
    return subprocess.run(
        ["sh", "-c", f". {shlex.quote(str(plugin / 'templates/hook-lib.sh'))}; run_tier full"],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
    )


def information(state, mode):
    for entry in state["full_tier_history"]:
        for key in ("started_at", "ended_at", "duration_seconds"):
            entry.pop(key, None)
        if mode == "malformed-timing":
            entry.update(started_at={"bad": True}, ended_at="2000-01-01", duration_seconds=-1)
        elif mode == "unknown-fields":
            entry["runner_info"] = {"anything": [1, 2]}
    if mode == "malformed-timing":
        variants = [
            {"started_at": "2026-09-22T00:00:00"},
            {"started_at": "2026-09-22T00:00:00+01:00"},
            {"started_at": "2026-09-22T00:00:00Z", "ended_at": "2000-01-01T00:00:00Z"},
            {"duration_seconds": True},
            {"duration_seconds": float("nan")},
            {"duration_seconds": float("inf")},
        ]
        state["full_tier_history"] = [
            dict(entry, **variant) for entry in state["full_tier_history"] for variant in variants
        ]
    state["full_tier"]["runner_info"] = True
    for component in state["full_tier"].get("components", []):
        component["runner_info"] = None


@pytest.mark.parametrize("failure", ["", "missing-env", "missing-adapter"])
def test_setup_directions_walk_full_tier(tmp_path, failure):
    repo, env = bare_repo(tmp_path)
    install = tmp_path / "installed plugin"
    shutil.copytree(PLUGIN, install)
    result = subprocess.run(
        [sys.executable, str(install / "scripts/setup.py")],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    events = tmp_path / "events"
    config = repo / ".xp/config.yml"
    config.write_text(
        "\n".join(
            line for line in config.read_text().splitlines() if not line.startswith("  full:")
        )
        + f"\nfull_legs:\n  first: printf first >> '{events}'\n"
        + f"  second: printf second >> '{events}'\n"
    )
    from session_start import config_age

    assert config_age(repo) == ""
    if failure == "missing-env":
        next((tmp_path / ".xp/data").glob("*/env.json")).unlink()
    elif failure == "missing-adapter":
        (install / "scripts/work.py").unlink()
    result = shell_full(repo, env, install)
    if failure:
        assert result.returncode != 0 and result.stderr
        assert not events.exists()
    else:
        assert result.returncode == 0, result.stderr
        assert events.read_text() == "firstsecond"


@pytest.mark.parametrize(
    "case", ["partial", "latest-red", "command", "tree", "metadata", "metadata-red"]
)
def test_post_merge_leg_reuse_controls(tmp_path, case):
    from sprint_helpers import CONFIG, make_repo

    events, flag = tmp_path / "events", tmp_path / "red"
    command = f"printf two >> '{events}'; test ! -e '{flag}'"
    config = CONFIG.replace("full: true", f"full: printf one >> '{events}' && {command}") + (
        f"full_legs:\n  one: printf one >> '{events}'\n  two: {command}\n"
    )
    repo, env, g = make_repo(tmp_path, config=config)
    record_reviews(tmp_path, repo, env)
    publishing(tmp_path, repo, env, g)
    result = sprint(repo, env, "land")
    assert result.returncode == 0, result.stdout + result.stderr
    saved = json.loads(marker_path(tmp_path).read_text())
    older = saved["full_tier"]
    if case in ("partial", "latest-red", "metadata-red"):
        saved["full_tier_history"].append(dict(saved["full_tier_history"][-1], outcome="failed"))
        saved.pop("full_tier")
        marker_path(tmp_path).write_text(json.dumps(saved))
        flag.touch()
        result = sprint(repo, env, "land")
        assert result.returncode == 2 and "test tier leg two" in result.stderr
        saved = json.loads(marker_path(tmp_path).read_text())
        if case != "partial":
            saved["full_tier"] = older
        if case == "partial":
            flag.unlink()
    if case in ("metadata", "metadata-red"):
        information(saved, "malformed-timing")
    marker_path(tmp_path).write_text(json.dumps(saved))
    assert g("checkout", "-q", "main").returncode == 0
    assert g("merge", "--no-ff", "sprint-002", "-m", "release").returncode == 0
    if case == "tree":
        (repo / "src.py").write_text("CHANGED = 1\n")
        assert g("commit", "-qam", "changed tree").returncode == 0
    elif case == "command":
        path = repo / ".xp/config.yml"
        path.write_text(path.read_text().replace(command, command + " && true"))
        assert g("commit", "-qam", "changed command").returncode == 0
    before = events.read_text()
    result = sprint(repo, env, "post-merge")
    delta = events.read_text()[len(before) :]
    assert delta == (
        "onetwo" if case in ("tree", "command") else "" if case == "metadata" else "two"
    )
    red = case in ("latest-red", "metadata-red")
    assert result.returncode == (2 if red else 0), result.stdout + result.stderr
    assert (tmp_path / "data/releases/sprint-2.json").exists() == (not red)
    assert bool(g("tag", "--list", "v0.3.0").stdout) == (not red)
    assert (tmp_path / "data/sprint_branch").exists() == red


@pytest.mark.parametrize("red", [False, True])
def test_closer_full_gate_directions_walk_release(tmp_path, red):
    from sprint_helpers import CONFIG, make_repo

    events = tmp_path / "events"
    command = f"printf x >> '{events}'; {'false' if red else 'true'}"
    repo, env, g = make_repo(
        tmp_path, config=CONFIG.replace("  full: true\n", "") + f"full_legs:\n  checks: {command}\n"
    )
    record_reviews(tmp_path, repo, env, blocking=["full check"])
    saved = json.loads(marker_path(tmp_path).read_text())
    saved["rounds"][-1]["clearable_by_full"] = ["full check"]
    marker_path(tmp_path).write_text(json.dumps(saved))
    publishing(tmp_path, repo, env, g)
    result = sprint(repo, env, "land")
    assert result.returncode == (2 if red else 0), result.stdout + result.stderr
    assert events.read_text() == "x"
    if red:
        assert json.loads(marker_path(tmp_path).read_text())["rounds"][-1]["blocking"]
        assert not (tmp_path / "data/releases/sprint-2.json").exists()
        assert not g("tag", "--list", "v0.3.0").stdout
    else:
        assert g("checkout", "-q", "main").returncode == 0
        assert g("merge", "--no-ff", "sprint-002", "-m", "release").returncode == 0
        result = sprint(repo, env, "post-merge")
        assert result.returncode == 0, result.stdout + result.stderr
        assert events.read_text() == "x"
        assert (tmp_path / "data/releases/sprint-2.json").exists()


@pytest.mark.meta
@pytest.mark.parametrize(
    "mode,nodes",
    [
        (
            "authority",
            [
                "test_tier_legs.py::test_shell_full_uses_authoritative_commands[stale-red]",
                "test_tier_legs.py::test_full_legs_override_stale_full_at_land[False-False]",
            ],
        ),
        ("compound", ["test_tier_legs.py::test_shell_full_uses_authoritative_commands[compound]"]),
        (
            "adapter",
            ["test_full_tier_consumers.py::test_setup_directions_walk_full_tier[missing-adapter]"],
        ),
        (
            "outcome",
            [
                "test_sprint_tier_history.py::test_corrupt_history_cannot_certify_receipt[<lambda>2]",
                "test_sprint_tier_history.py::test_corrupt_history_cannot_certify_receipt[<lambda>5]",
            ],
        ),
        (
            "latest",
            [
                "test_tier_legs.py::test_latest_matching_failure_reruns_leg",
                "test_full_tier_consumers.py::test_post_merge_leg_reuse_controls[latest-red]",
            ],
        ),
        (
            "tree",
            [
                "test_tier_legs.py::test_changed_tree_reruns_every_leg",
                "test_full_tier_consumers.py::test_post_merge_leg_reuse_controls[tree]",
            ],
        ),
        ("command", ["test_tier_legs.py::test_changed_leg_command_reruns_only_that_leg"]),
        (
            "locked",
            [
                "test_tier_legs.py::test_leg_reuse_append_rechecks_latest_outcome_under_lock",
                "test_sprint_tier_history.py::test_reuse_append_rechecks_latest_outcome_under_lock",
            ],
        ),
        (
            "publish",
            ["test_full_tier_consumers.py::test_post_merge_leg_reuse_controls[latest-red]"],
        ),
        (
            "timing",
            [
                "test_full_tier_consumers.py::test_post_merge_leg_reuse_controls[metadata]",
                "test_sprint_tier_history.py::test_land_ignores_informational_metadata[malformed-timing]",
            ],
        ),
        (
            "receipt-info",
            [
                "test_sprint_tier_history.py::test_land_ignores_informational_metadata[unknown-fields]",
                "test_tier_legs.py::test_receipt_components_must_join_to_the_command",
            ],
        ),
    ],
    ids=[
        "authority",
        "compound",
        "adapter",
        "outcome",
        "latest",
        "tree",
        "command",
        "locked",
        "publish",
        "timing",
        "receipt-info",
    ],
)
def test_changed_guards_reject_target_defects(tmp_path, mode, nodes):
    import os

    root = tmp_path / "mutation"
    root.mkdir()
    shutil.copytree(
        PLUGIN, root / "plugins/xp-plugin", ignore=shutil.ignore_patterns("__pycache__")
    )
    shutil.copytree(
        PLUGIN.parents[1] / "tests", root / "tests", ignore=shutil.ignore_patterns("__pycache__")
    )
    shutil.copy(PLUGIN.parents[1] / "pytest.ini", root / "pytest.ini")
    scripts = root / "plugins/xp-plugin/scripts"

    def replace(path, old, new):
        source = path.read_text()
        assert old in source
        path.write_text(source.replace(old, new))

    legs = scripts / "close/tier_legs.py"
    state = scripts / "close/sprint_state.py"
    overlap = scripts / "close/overlap.py"
    if mode == "authority":
        replace(
            legs,
            'return compose(legs) if legs is not None else config_block_value("tests", "full")',
            'return config_block_value("tests", "full")',
        )
    elif mode == "compound":
        replace(legs, 'f"({command})"', "command")
    elif mode == "adapter":
        replace(
            root / "plugins/xp-plugin/templates/hook-lib.sh",
            'python3 "$adapter" tier full',
            'python3 "$adapter" tier full || printf true',
        )
    elif mode == "outcome":
        replace(state, 'and entry.get("outcome") in ("passed", "failed", "reused")', "and True")
    elif mode == "latest":
        replace(legs, "reversed(history)", "history")
        replace(state, "reversed(history)", "history")
    elif mode in ("tree", "command"):
        old = '(item["leg"], item["command"], item["tree"]) == (name, command, tree)'
        new = 'item["leg"] == name and ' + (
            'item["command"] == command' if mode == "tree" else 'item["tree"] == tree'
        )
        replace(legs, old, new)
    elif mode == "locked":
        replace(state, "        if veto:\n", "        if False:\n")
    elif mode == "publish":
        path = scripts / "close/shipping.py"
        source = path.read_text()
        start = source.index("    error, receipt = overlap.gates(")
        end = source.index("    if error:", start)
        path.write_text(
            source[:start] + '    error, receipt = "", state["full_tier"]\n' + source[end:]
        )
        replace(path, "if error := validation_refusal(accepted, receipt, before):", "if False:")
    elif mode == "timing":
        replace(
            state,
            'and entry.get("outcome")',
            'and entry.get("duration_seconds", -1) >= 0\n            and entry.get("outcome")',
        )
    elif mode == "receipt-info":
        replace(overlap, "and set(receipt) >= _RECEIPT_KEYS", "and set(receipt) == _RECEIPT_KEYS")
    env = os.environ.copy()
    for key in ("PYTEST_ADDOPTS", "PYTEST_XDIST_WORKER", "PYTEST_XDIST_WORKER_COUNT"):
        env.pop(key, None)
    for node in nodes:
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "-n", "4", f"tests/{node}"],
            cwd=root,
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert result.returncode == 1, result.stdout + result.stderr
        assert "AssertionError" in result.stdout or "DID NOT RAISE" in result.stdout, (
            result.stdout + result.stderr
        )
