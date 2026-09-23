"""Ordered full-tier legs and evidence on sprint land."""

import importlib
import json

import pytest
from sprint_helpers import CONFIG, make_repo, marker_path, record_reviews, sprint
from test_sprint_tier_receipt import add_origin, advance_origin


def configured(tmp_path, names_commands):
    block = "full_legs:\n" + "".join(f"  {name}: {cmd}\n" for name, cmd in names_commands)
    joined = " && ".join(cmd for _, cmd in names_commands)
    config = CONFIG.replace("full: true", f"full: {joined}") + block
    repo, env, g = make_repo(tmp_path, config=config)
    record_reviews(tmp_path, repo, env)
    return repo, env, g


def state(tmp_path):
    return json.loads(marker_path(tmp_path).read_text())


def test_failed_second_leg_resumes_only_second(tmp_path):
    first, second, ready = (tmp_path / n for n in ("first", "second", "ready"))
    repo, env, _g = configured(
        tmp_path,
        [("one", f"printf x >> {first}"), ("two", f"printf x >> {second}; test -e {ready}")],
    )

    assert sprint(repo, env, "land").returncode == 2
    assert [e["outcome"] for e in state(tmp_path)["full_tier_history"]] == ["passed", "failed"]
    ready.touch()
    assert sprint(repo, env, "land").returncode == 2

    assert first.read_text() == "x" and second.read_text() == "xx"
    saved = state(tmp_path)
    assert [(e["leg"], e["outcome"]) for e in saved["full_tier_history"]] == [
        ("one", "passed"),
        ("two", "failed"),
        ("one", "reused"),
        ("two", "passed"),
    ]
    assert [c["status"] for c in saved["full_tier"]["components"]] == ["reused", "ran"]


@pytest.mark.parametrize(
    "names,reason",
    [
        ([("one", "true"), ("one", "true")], "duplicate"),
        ([("land", "true")], "reserved"),
        ([("start", "true")], "reserved"),
    ],
)
def test_invalid_legs_refuse_before_history(tmp_path, names, reason):
    repo, env, _g = configured(tmp_path, names)
    marker = marker_path(tmp_path)
    saved = state(tmp_path)
    saved["full_tier_history"] = "bad"
    marker.write_text(json.dumps(saved))
    for args in (("land",), ("land", "--dry-run")):
        result = sprint(repo, env, *args)
        assert result.returncode == 2 and reason in result.stderr
        assert "history" not in result.stderr


def test_all_green_reland_reuses_every_leg(tmp_path):
    first, second = (tmp_path / n for n in ("first", "second"))
    repo, env, _g = configured(
        tmp_path, [("one", f"printf x >> {first}"), ("two", f"printf x >> {second}")]
    )
    assert sprint(repo, env, "land").returncode == 2
    again = sprint(repo, env, "land")
    assert again.returncode == 2 and "receipt contradicts" not in again.stderr
    third = sprint(repo, env, "land")
    assert third.returncode == 2 and "receipt contradicts" not in third.stderr
    assert first.read_text() == second.read_text() == "x"
    assert [e["outcome"] for e in state(tmp_path)["full_tier_history"]] == [
        "passed",
        "passed",
        "reused",
        "reused",
        "reused",
        "reused",
    ]
    assert [c["status"] for c in state(tmp_path)["full_tier"]["components"]] == ["reused", "reused"]


@pytest.mark.parametrize("dry", [False, True])
def test_join_mismatch_refuses_before_history(tmp_path, dry):
    first = tmp_path / "first"
    repo, env, _g = configured(tmp_path, [("one", f"touch {first}")])
    cfg = repo / ".xp/config.yml"
    cfg.write_text(cfg.read_text().replace(f"full: touch {first}", "full: true"))
    marker = marker_path(tmp_path)
    saved = state(tmp_path)
    saved["full_tier_history"] = "bad"
    marker.write_text(json.dumps(saved))
    result = sprint(repo, env, "land", *(("--dry-run",) if dry else ()))
    assert result.returncode == 2 and "join mismatch" in result.stderr
    assert "tests.full='true'" in result.stderr and not first.exists()


def test_dry_run_lists_declared_legs(tmp_path):
    repo, env, _g = configured(tmp_path, [("one", "true"), ("two", "true")])
    result = sprint(repo, env, "land", "--dry-run")
    assert result.returncode == 0
    assert result.stdout.index("leg one: true") < result.stdout.index("leg two: true")


def test_missing_command_records_no_second_event(tmp_path):
    first = tmp_path / "first"
    command = "command-that-cannot-exist-xp-147"
    repo, env, _g = configured(tmp_path, [("one", f"printf x >> {first}"), ("two", command)])
    result = sprint(repo, env, "land")
    assert result.returncode == 2 and "could not run" in result.stderr
    assert [(e["leg"], e["outcome"]) for e in state(tmp_path)["full_tier_history"]] == [
        ("one", "passed")
    ]
    executable = tmp_path / "bin" / command
    executable.write_text("#!/bin/sh\nexit 0\n")
    executable.chmod(0o755)
    assert sprint(repo, env, "land").returncode == 2
    assert first.read_text() == "x"
    assert [e["outcome"] for e in state(tmp_path)["full_tier_history"]][-2:] == ["reused", "passed"]


def test_signal_records_no_second_event(tmp_path):
    first = tmp_path / "first"
    ready = tmp_path / "ready"
    repo, env, _g = configured(
        tmp_path,
        [("one", f"printf x >> {first}"), ("two", f"test -e {ready} || kill -TERM $$")],
    )
    result = sprint(repo, env, "land")
    assert result.returncode == 2 and "signal" in result.stderr
    assert [(e["leg"], e["outcome"]) for e in state(tmp_path)["full_tier_history"]] == [
        ("one", "passed")
    ]
    ready.touch()
    assert sprint(repo, env, "land").returncode == 2
    assert first.read_text() == "x"


def test_undeclared_history_leg_refuses_with_remedy(tmp_path):
    repo, env, _g = configured(tmp_path, [("one", "true")])
    assert sprint(repo, env, "land").returncode == 2
    marker = marker_path(tmp_path)
    saved = state(tmp_path)
    saved["full_tier_history"][0]["leg"] = "removed"
    marker.write_text(json.dumps(saved))
    result = sprint(repo, env, "land")
    assert result.returncode == 2 and "full_tier_history" in result.stderr
    assert "repair or delete" in result.stderr


def test_changed_tree_reruns_every_leg(tmp_path):
    first, second = (tmp_path / n for n in ("first", "second"))
    repo, env, g = configured(
        tmp_path,
        [("one", f"printf x >> {first}"), ("two", f"printf x >> {second}")],
    )
    assert sprint(repo, env, "land").returncode == 2
    (repo / "src.py").write_text("A = 2\n")
    assert g("add", "src.py").returncode == 0
    assert g("commit", "-qm", "new tree").returncode == 0
    record_reviews(tmp_path, repo, env)
    assert sprint(repo, env, "land").returncode == 2
    assert first.read_text() == second.read_text() == "xx"


def test_latest_matching_failure_reruns_leg(tmp_path):
    first, second = (tmp_path / n for n in ("first", "second"))
    repo, env, _g = configured(
        tmp_path,
        [("one", f"printf x >> {first}"), ("two", f"printf x >> {second}")],
    )
    assert sprint(repo, env, "land").returncode == 2
    marker = marker_path(tmp_path)
    saved = state(tmp_path)
    saved["full_tier_history"].append(dict(saved["full_tier_history"][1], outcome="failed"))
    marker.write_text(json.dumps(saved))
    assert sprint(repo, env, "land").returncode == 2
    assert first.read_text() == "x" and second.read_text() == "xx"
    assert [e["outcome"] for e in state(tmp_path)["full_tier_history"]][-2:] == ["reused", "passed"]


def test_changed_leg_command_reruns_only_that_leg(tmp_path):
    first, second = (tmp_path / n for n in ("first", "second"))
    repo, env, _g = configured(
        tmp_path,
        [("one", f"printf x >> {first}"), ("two", f"printf x >> {second}")],
    )
    assert sprint(repo, env, "land").returncode == 2
    marker = marker_path(tmp_path)
    saved = state(tmp_path)
    saved["full_tier_history"][1]["command"] = "an earlier spelling of leg two"
    marker.write_text(json.dumps(saved))
    assert sprint(repo, env, "land").returncode == 2
    assert first.read_text() == "x" and second.read_text() == "xx"


def test_leg_reuse_append_rechecks_latest_outcome_under_lock(tmp_path, monkeypatch):
    sprint_state = importlib.import_module("sprint_state")
    repo, env, _g = configured(tmp_path, [("one", "true"), ("two", "true")])
    assert sprint(repo, env, "land").returncode == 2
    marker = marker_path(tmp_path)
    saved = state(tmp_path)
    failed = dict(saved["full_tier_history"][0], outcome="failed")
    saved["full_tier_history"].append(failed)
    marker.write_text(json.dumps(saved))
    monkeypatch.setattr(sprint_state, "data_root", lambda: tmp_path / "data")

    with pytest.raises(ValueError, match="latest outcome failed"):
        sprint_state.append_tier_evidence(
            marker, dict(failed, outcome="reused"), None, ("one", "two")
        )
    assert state(tmp_path) == saved


def test_receipt_components_must_join_to_the_command():
    overlap = importlib.import_module("overlap")
    component = {"leg": "one", "command": "a", "status": "ran", "head": "h"}
    receipt = {
        "tier": "full",
        "command": "a && b",
        "tree": "t",
        "head": "h",
        "verdict": "passed",
        "ran_by": "land",
        "reused": False,
        "components": [component, dict(component, leg="two", command="b")],
    }
    assert overlap._receipt_matches(receipt, "a && b", "t") == (True, "reused")
    receipt["components"][1]["command"] = "c"
    assert overlap._receipt_matches(receipt, "a && b", "t") == (False, "unreadable")


def test_dirty_tree_is_named_before_the_trial_merge(tmp_path):
    repo, env, g = configured(tmp_path, [("one", "true")])
    add_origin(tmp_path, repo, env, g)
    advance_origin(repo, g, "trunk-only", "present\n")
    (repo / "src.py").write_text("A = 3\n")
    assert g("add", "src.py").returncode == 0
    for args in (("land",), ("land", "--dry-run")):
        result = sprint(repo, env, *args)
        assert result.returncode == 2 and "dirty" in result.stderr and "src.py" in result.stderr


def test_commented_full_legs_keeps_dry_run_off_the_trial_merge(tmp_path):
    repo, env, g = make_repo(tmp_path, config=CONFIG + "# full_legs:\n#   one: true\n")
    record_reviews(tmp_path, repo, env)
    add_origin(tmp_path, repo, env, g)
    advance_origin(repo, g, "trunk-only", "present\n")
    (repo / "src.py").write_text("A = 3\n")
    assert g("add", "src.py").returncode == 0
    assert sprint(repo, env, "land", "--dry-run").returncode == 0
