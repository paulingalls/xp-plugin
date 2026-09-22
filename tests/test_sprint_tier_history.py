"""Measured sprint tier attempts survive land re-entry."""

import importlib
import json
from datetime import datetime, timezone

import pytest
from sprint_helpers import make_repo, marker_path, record_reviews, sprint, staged_stub
from test_sprint_tier_receipt import counted_repo, run_count, state, tree
from test_tier_coverage import config, covered_debt


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


@pytest.mark.parametrize(
    "corrupt",
    (
        lambda h: [{"outcome": "passed"}],
        lambda h: 7,
        lambda h: [dict(h[0], outcome="passd")],
        lambda h: [dict(h[0], leg="start")],
        lambda h: [dict(h[0], tree="")],
        lambda h: [dict(h[0], duration_seconds=-1)],
        lambda h: [dict(h[0], duration_seconds=True)],
        lambda h: [dict(h[0], started_at="2026-09-22T00:00:00")],
        lambda h: [dict(h[0], started_at="2026-09-22T00:00:00+01:00")],
        lambda h: [dict(h[0], ended_at="2000-01-01T00:00:00Z")],
    ),
)
def test_corrupt_history_cannot_certify_receipt(tmp_path, corrupt):
    repo, env, _g, events, _tier = counted_repo(tmp_path)
    record_reviews(tmp_path, repo, env)
    assert sprint(repo, env, "land").returncode == 2
    marker = marker_path(tmp_path)
    saved = state(tmp_path)
    saved["full_tier_history"] = corrupt(saved["full_tier_history"])
    marker.write_text(json.dumps(saved))
    before = marker.read_bytes()

    result = sprint(repo, env, "land")

    assert result.returncode == 2 and "unreadable full_tier_history" in result.stderr
    assert marker.read_bytes() == before and run_count(events) == 1


@pytest.mark.parametrize("value", ["F-1", [1]])
def test_unreadable_start_deferred_ids_refuses_before_the_tier(tmp_path, value):
    """A string would turn `eid in start_ids` into a substring match."""
    repo, env, _g, events, _tier = counted_repo(tmp_path)
    record_reviews(tmp_path, repo, env)
    marker = marker_path(tmp_path)
    saved = state(tmp_path)
    saved["start_deferred_ids"] = value
    marker.write_text(json.dumps(saved))

    result = sprint(repo, env, "land")

    assert result.returncode == 2 and "unreadable start_deferred_ids" in result.stderr
    assert "sprint 2 start" in result.stderr and run_count(events) == 0


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


def test_round_recorded_during_the_falsifier_batch_gates_land(tmp_path):
    script, flag = tmp_path / "falsifier.py", tmp_path / "armed"
    script.write_text(
        "import json, pathlib\n"
        f"marker = pathlib.Path({str(marker_path(tmp_path))!r})\n"
        f"if not pathlib.Path({str(flag)!r}).exists():\n"
        "    raise SystemExit(0)\n"
        "state = json.loads(marker.read_text())\n"
        "state['rounds'].append({'incomplete': 'concurrent round', 'blocking': []})\n"
        "marker.write_text(json.dumps(state))\n"
    )
    full = f"printf x >> {tmp_path / 'full'}"
    tiers = (("fast", "true"), ("full", full))
    cfg = config(tiers, (("fast", "full"),), tiers)
    repo, env, g = make_repo(tmp_path, config=cfg)
    covered_debt(repo, env, f"python3 {script}", "fast")
    assert sprint(repo, env, "start").returncode == 0
    (repo / ".xp/config.yml").write_text(cfg.replace("tier_coverage:\n  fast: full\n", ""))
    g("commit", "-qam", "remove coverage")
    record_reviews(tmp_path, repo, env)
    flag.touch()

    result = sprint(repo, env, "land")

    assert result.returncode == 2 and "concurrent round" in result.stderr


@pytest.mark.parametrize(
    ("field", "reason"),
    (
        ("tree", "no matching history entry"),
        ("head", "contradicts full_tier_history"),
        ("command", "contradicts full_tier_history"),
    ),
)
def test_history_that_does_not_vouch_for_the_receipt_refuses_reuse(tmp_path, field, reason):
    repo, env, _g, events, _tier = counted_repo(tmp_path)
    record_reviews(tmp_path, repo, env)
    assert sprint(repo, env, "land").returncode == 2
    marker = marker_path(tmp_path)
    saved = state(tmp_path)
    saved["full_tier_history"][-1][field] = "0" * 40
    marker.write_text(json.dumps(saved))
    before = marker.read_bytes()

    result = sprint(repo, env, "land")

    assert result.returncode == 2 and reason in result.stderr
    assert "delete full_tier" in result.stderr
    assert marker.read_bytes() == before and run_count(events) == 1
