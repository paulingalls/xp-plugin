"""Measured sprint tier attempts survive land re-entry."""

import importlib
import json
from datetime import datetime, timezone

import pytest
from sprint_helpers import marker_path, record_reviews, sprint, staged_stub
from test_sprint_tier_receipt import counted_repo, run_count, state, tree


def test_reentry_records_reuse_without_running_again(tmp_path):
    repo, env, g, events, tier = counted_repo(tmp_path)
    staged_stub(tmp_path)
    assert sprint(repo, env, "start").returncode == 0
    assert sprint(repo, env, "review").returncode == 0
    assert sprint(repo, env, "land").returncode == 2
    assert sprint(repo, env, "land").returncode == 2
    saved = state(tmp_path)
    assert run_count(events) == 1
    assert set(saved["full_tier"]) == {
        "tier",
        "command",
        "tree",
        "head",
        "verdict",
        "ran_by",
        "reused",
    }
    history = saved["full_tier_history"]
    assert [entry["outcome"] for entry in history] == ["passed", "reused"]
    assert all(entry["leg"] == "land" and entry["command"] == tier for entry in history)
    assert all(entry["tree"] == tree(g) for entry in history)
    for entry in history:
        start = datetime.fromisoformat(entry["started_at"].replace("Z", "+00:00"))
        end = datetime.fromisoformat(entry["ended_at"].replace("Z", "+00:00"))
        assert start.tzinfo == timezone.utc and end.tzinfo == timezone.utc and end >= start
        assert 0 <= entry["duration_seconds"] < 60


def test_pass_then_fail_vetoes_reuse(tmp_path):
    flag = tmp_path / "red"
    events = tmp_path / "events"
    repo, env, g, _events, tier = counted_repo(tmp_path, f"printf x >> {events}; test ! -e {flag}")
    record_reviews(tmp_path, repo, env)
    assert sprint(repo, env, "land").returncode == 2
    marker = marker_path(tmp_path)
    saved = state(tmp_path)
    passed_receipt = saved.pop("full_tier")
    marker.write_text(json.dumps(saved))
    flag.touch()
    assert sprint(repo, env, "land").returncode == 2
    assert [e["outcome"] for e in state(tmp_path)["full_tier_history"]] == ["passed", "failed"]
    assert all(
        e["tree"] == tree(g) and e["command"] == tier for e in state(tmp_path)["full_tier_history"]
    )
    saved = state(tmp_path)
    saved["full_tier"] = passed_receipt
    marker.write_text(json.dumps(saved))
    assert sprint(repo, env, "land").returncode == 2
    assert events.read_text() == "xxx"
    assert state(tmp_path)["full_tier_history"][-1]["outcome"] == "failed"


def test_fail_then_pass_reuses_latest_pass(tmp_path):
    flag = tmp_path / "red"
    events = tmp_path / "events"
    repo, env, _g, _events, _tier = counted_repo(
        tmp_path, f"printf x >> {events}; test ! -e {flag}"
    )
    record_reviews(tmp_path, repo, env)
    flag.touch()
    assert sprint(repo, env, "land").returncode == 2
    flag.unlink()
    assert sprint(repo, env, "land").returncode == 2
    assert sprint(repo, env, "land").returncode == 2
    assert events.read_text() == "xx"
    assert [e["outcome"] for e in state(tmp_path)["full_tier_history"]] == [
        "failed",
        "passed",
        "reused",
    ]


def test_corrupt_history_cannot_certify_receipt(tmp_path):
    repo, env, _g, events, _tier = counted_repo(tmp_path)
    record_reviews(tmp_path, repo, env)
    assert sprint(repo, env, "land").returncode == 2
    marker = marker_path(tmp_path)
    saved = state(tmp_path)
    saved["full_tier_history"] = [{"outcome": "passed"}]
    marker.write_text(json.dumps(saved))
    before = marker.read_bytes()

    result = sprint(repo, env, "land")

    assert result.returncode == 2 and "unreadable full_tier_history" in result.stderr
    assert marker.read_bytes() == before and run_count(events) == 1


def test_unmeasured_refusals_preserve_history(tmp_path):
    repo, env, _g, events, _tier = counted_repo(tmp_path)
    record_reviews(tmp_path, repo, env)
    assert sprint(repo, env, "land").returncode == 2
    marker = marker_path(tmp_path)
    before = marker.read_bytes()
    (repo / ".git/index.lock").touch()

    result = sprint(repo, env, "land")

    assert result.returncode == 2 and "write tree" in result.stderr.lower()
    assert marker.read_bytes() == before and run_count(events) == 1


def test_unreadable_receipt_runs_again_without_changing_history_shape(tmp_path):
    repo, env, _g, events, _tier = counted_repo(tmp_path)
    record_reviews(tmp_path, repo, env)
    assert sprint(repo, env, "land").returncode == 2
    marker = marker_path(tmp_path)
    saved = state(tmp_path)
    saved["full_tier"]["full_tier_history"] = saved["full_tier_history"]
    marker.write_text(json.dumps(saved))

    result = sprint(repo, env, "land")

    assert "unreadable" in result.stdout.splitlines()[0]
    assert run_count(events) == 2
    assert [e["outcome"] for e in state(tmp_path)["full_tier_history"]] == ["passed", "passed"]


def test_signalled_shell_does_not_record_a_failed_tier(tmp_path):
    repo, env, _g, _events, _tier = counted_repo(tmp_path, "kill -TERM $$")
    record_reviews(tmp_path, repo, env)

    result = sprint(repo, env, "land")

    assert result.returncode == 2 and "interrupted" in result.stderr
    assert "full_tier_history" not in state(tmp_path)


def test_reuse_append_rechecks_latest_outcome_under_lock(tmp_path, monkeypatch):
    sprint_state = importlib.import_module("sprint_state")
    repo, env, _g, _events, _tier = counted_repo(tmp_path)
    record_reviews(tmp_path, repo, env)
    assert sprint(repo, env, "land").returncode == 2
    marker = marker_path(tmp_path)
    saved = state(tmp_path)
    failed = dict(saved["full_tier_history"][-1], outcome="failed")
    saved["full_tier_history"].append(failed)
    marker.write_text(json.dumps(saved))
    monkeypatch.setattr(sprint_state, "data_root", lambda: tmp_path / "data")

    with pytest.raises(ValueError, match="latest outcome failed"):
        sprint_state.append_tier_evidence(
            marker, dict(failed, outcome="reused"), dict(saved["full_tier"], reused=True)
        )
    assert state(tmp_path) == saved
