"""Timing rows are durable telemetry and interval totals use the union."""

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone

from timing import Span, release_start, table


def test_span_writes_one_utc_row_and_warns_without_failing(tmp_path, capsys):
    span = Span(tmp_path, "agent", "story-148-reviewer")
    span.finish("passed")
    row = json.loads((tmp_path / "timing.jsonl").read_text())
    assert row["kind"] == "agent" and row["name"] == "story-148-reviewer"
    assert row["outcome"] == "passed" and row["duration_seconds"] > 0
    assert datetime.fromisoformat(row["started_at"]).utcoffset() == timedelta(0)
    blocked = tmp_path / "blocked"
    blocked.write_text("file")
    Span(blocked, "agent", "test").finish("failed")
    assert "timing.jsonl" in capsys.readouterr().err


def test_release_window_uses_union_and_reports_idle(tmp_path):
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    releases = tmp_path / "releases"
    releases.mkdir()
    (releases / "sprint-1.json").write_text(json.dumps({"released_at": base.isoformat()}))
    intervals = [(-1, 1), (5, 15), (5, 15), (45, 50)]
    with (tmp_path / "timing.jsonl").open("w") as stream:
        for index, (begin, end) in enumerate(intervals):
            stream.write(
                json.dumps(
                    {
                        "kind": "agent",
                        "name": f"run {index}",
                        "outcome": "passed",
                        "started_at": (base + timedelta(minutes=begin)).isoformat(),
                        "ended_at": (base + timedelta(minutes=end)).isoformat(),
                    }
                )
                + "\n"
            )
    shown = table(tmp_path)
    assert "run 0" not in shown
    assert shown.count("agent |") == 3
    assert "ACTIVE 900.0s" in shown
    assert "CALENDAR 2700.0s" in shown
    assert "idle — awaiting human or CI (not distinguished): 1800.0s" in shown


def test_first_sprint_is_labelled_and_includes_every_event(tmp_path):
    Span(tmp_path, "agent", "first").finish("passed")
    shown = table(tmp_path)
    assert "no release yet" in shown and "first" in shown


def test_released_at_precedes_legacy_tag_lookup(tmp_path):
    releases = tmp_path / "releases"
    releases.mkdir()
    stamp = datetime(2026, 1, 1, tzinfo=timezone.utc)
    (releases / "sprint-1.json").write_text(
        json.dumps({"released_at": stamp.isoformat(), "tag": "missing"})
    )
    assert release_start(tmp_path) == stamp


def test_agent_run_writes_a_timing_row(tmp_path):
    from teammate_tee import run_stream

    line = json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": "ok"}})
    result = run_stream(
        [sys.executable, "-c", f"print({line!r})"],
        tmp_path,
        "",
        "story-148-reviewer",
        tmp_path / "data",
        "codex",
        os.environ.copy(),
    )
    assert result.returncode == 0
    row = json.loads((tmp_path / "data" / "timing.jsonl").read_text())
    assert row["kind"] == "agent" and row["outcome"] == "passed"


def test_old_record_uses_tag_date_and_never_file_mtime(tmp_path, monkeypatch):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "config", "user.email", "test@example.com"], check=True
    )
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", "Test"], check=True)
    env = os.environ | {
        "GIT_AUTHOR_DATE": "2020-01-02T03:04:05+00:00",
        "GIT_COMMITTER_DATE": "2020-01-02T03:04:05+00:00",
    }
    (tmp_path / "a").write_text("a")
    subprocess.run(["git", "-C", str(tmp_path), "add", "a"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-qm", "first"], env=env, check=True)
    subprocess.run(["git", "-C", str(tmp_path), "tag", "v1.0.0"], check=True)
    releases = tmp_path / "releases"
    releases.mkdir()
    record = releases / "sprint-1.json"
    record.write_text(json.dumps({"tag": "v1.0.0"}))
    os.utime(record, (1_900_000_000, 1_900_000_000))
    monkeypatch.chdir(tmp_path)
    assert release_start(tmp_path) == datetime(2020, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
    record.write_text(json.dumps({"tag": "missing"}))
    try:
        release_start(tmp_path)
    except ValueError as exc:
        assert "no creation date" in str(exc)
    else:
        raise AssertionError("missing tag was silently accepted")


def test_start_and_milestone_write_distinct_rows(tmp_path):
    from sprint_helpers import make_repo, sprint
    from test_milestone import active_plan

    repo, env, _g = make_repo(tmp_path, plan=active_plan())
    assert sprint(repo, env, "start").returncode == 0
    assert sprint(repo, env, "milestone-done").returncode == 0
    ledger = tmp_path / "data" / "timing.jsonl"
    rows = [json.loads(line) for line in ledger.read_text().splitlines()]
    assert [row["kind"] for row in rows] == ["falsifier-batch", "milestone"]
    assert all(row["outcome"] == "passed" and row["duration_seconds"] > 0 for row in rows)


def test_post_merge_prints_prior_window_and_then_records_release(tmp_path):
    from sprint_helpers import sprint
    from test_sprint_released import release_path, released_repo

    repo, env, _g = released_repo(tmp_path)
    root = tmp_path / "data"
    Span(root, "agent", "prior-release-window").finish("passed")
    result = sprint(repo, env, "post-merge", sprint_id="002")
    assert result.returncode == 0, result.stderr
    assert "prior-release-window" in result.stdout
    assert "no release yet" in result.stdout
    assert release_path(tmp_path).is_file()


def test_story_land_gates_write_a_timing_row(tmp_path):
    from close_helpers import close, worktree_land_setup

    _repo, env, _g, tree, _branch = worktree_land_setup(tmp_path)
    result = close(tree, env, "land")
    assert result.returncode == 0, result.stderr
    rows = [
        json.loads(line) for line in (tmp_path / "data" / "timing.jsonl").read_text().splitlines()
    ]
    gates = [row for row in rows if row["kind"] == "story-land-gates"]
    assert len(gates) == 1
    assert gates[0]["outcome"] == "passed" and gates[0]["duration_seconds"] > 0
