"""Ordered full-tier legs and evidence on sprint land."""

import json

import pytest
from sprint_helpers import CONFIG, make_repo, marker_path, record_reviews, sprint


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
    assert first.read_text() == second.read_text() == "x"
    assert [e["outcome"] for e in state(tmp_path)["full_tier_history"]] == [
        "passed",
        "passed",
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
