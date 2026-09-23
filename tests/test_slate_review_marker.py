"""Slate review marker state at recovery and the first sprint open."""

import json
import os
import shlex
import subprocess
import sys
from datetime import datetime, timezone

import pytest
from session_start_helpers import next_lines, run_recovery, xp_repo
from sprint_helpers import PLAN, make_repo, sprint


def _sleeping():
    return subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])


def _stop(child):
    child.terminate()
    child.wait(timeout=5)


@pytest.mark.parametrize(
    "pid_state", ["live", "dead", "absent", "malformed", "unreadable", "foreign"]
)
def test_recovery_distinguishes_slate_pid_states(tmp_path, pid_state):
    if pid_state == "foreign" and os.geteuid() == 0:
        pytest.skip("root may signal pid 1, so it cannot stand for another user's process")
    repo, _g = xp_repo(tmp_path)
    root = tmp_path / "xp"
    (root / "plan.md").write_text("# plan\n### Sprint 1\n#### story-042 — planned   [planned]\n")
    marker = root / "markers" / "1.slate-review-incomplete"
    marker.parent.mkdir()
    child = _sleeping()
    try:
        if pid_state == "dead":
            _stop(child)
        pid = {"live": child.pid, "dead": child.pid, "malformed": "bad", "foreign": 1}.get(
            pid_state
        )
        marker.write_text(
            "[]"
            if pid_state == "unreadable"
            else json.dumps({"pid": pid} if pid is not None else {})
        )
        lines = next_lines(run_recovery(repo, tmp_path).stdout)
        expected = (
            f"NEXT: Sprint 1 slate review running (pid {child.pid})"
            " — run `slate_review.py 1` to join it"
            if pid_state == "live"
            else "NEXT: Sprint 1 slate review incomplete — run `slate_review.py 1`"
        )
        assert lines == [expected]
    finally:
        if child.poll() is None:
            _stop(child)


def _open_fixture(tmp_path, pid=None):
    plan = PLAN.replace("#### story-042 — done thing   [done]", "#### story-042 — work   [planned]")
    repo, env, g = make_repo(tmp_path, plan=plan)
    root = tmp_path / "data"
    (root / "sprint_branch").unlink()
    findings = root / "slate-reviews" / "sprint-2.round-2.md"
    findings.parent.mkdir()
    (findings.parent / "sprint-2.round-1.md").write_text("complete round\n")
    findings.write_text("half-written round\n")
    log = root / "logs" / "2-slate-review.log"
    log.parent.mkdir()
    log.write_bytes(b"log stays\n")
    marker = root / "markers" / "2.slate-review-incomplete"
    marker.parent.mkdir()
    marker.write_text(
        json.dumps(
            {
                "pid": pid or 99999999,
                "findings": str(findings),
                "log": str(log),
                "next": "run python3 /script/slate_review.py 2",
            }
        )
    )
    return repo, env, g, root, marker, findings, log


def _lifecycle(repo, g, script):
    config = repo / ".xp" / "config.yml"
    config.write_text(
        f"lifecycle_command: {shlex.join([sys.executable, str(script)])}\n" + config.read_text()
    )
    g("add", "-A")
    g("commit", "-qm", "configure lifecycle")


def test_dead_marker_open_preserves_round_count_and_log(tmp_path, monkeypatch):
    repo, env, _g, root, marker, findings, log = _open_fixture(tmp_path)
    monkeypatch.setenv("XP_DATA", str(root))
    from review_runner import completed_review_rounds, review_is_capped

    assert [n for n, _ in completed_review_rounds("2", "slate")] == [1]
    result = sprint(repo, env, "start")

    assert result.returncode == 0, result.stderr
    assert not marker.exists()
    retired = list(marker.parent.glob(marker.name + ".superseded-*.json"))
    assert len(retired) == 1
    state = json.loads(retired[0].read_text())
    assert state["state"] == "superseded" and state["reason"]
    assert datetime.fromisoformat(state["timestamp"]).tzinfo == timezone.utc
    assert state["next"] == "run python3 /script/slate_review.py 2"
    assert not findings.exists()
    assert len(list(findings.parent.glob("sprint-2.round-2.failed-*.md"))) == 1
    assert [n for n, _ in completed_review_rounds("2", "slate")] == [1]
    assert not review_is_capped("2", "slate")
    assert log.read_bytes() == b"log stays\n"
    assert (
        "slate review"
        not in run_recovery(repo, tmp_path, data_dir=root)
        .stdout.split("NEXT:", 1)[1]
        .splitlines()[0]
    )


def test_open_archives_only_a_round_the_marker_hides(tmp_path):
    repo, env, _g, _root, marker, findings, _log = _open_fixture(tmp_path)
    foreign = tmp_path / "foreign.md"
    foreign.write_text("not a round\n")
    marker.write_text(json.dumps(json.loads(marker.read_text()) | {"findings": str(foreign)}))

    assert sprint(repo, env, "start").returncode == 0
    assert not marker.exists()
    assert foreign.read_text() == "not a round\n"
    assert findings.read_text() == "half-written round\n"


def test_live_marker_refuses_open_before_hook(tmp_path):
    child = _sleeping()
    try:
        repo, env, g, root, marker, findings, _log = _open_fixture(tmp_path, child.pid)
        sentinel = tmp_path / "hook-ran"
        script = tmp_path / "hook.py"
        script.write_text(f"from pathlib import Path\nPath({str(sentinel)!r}).write_text('ran')\n")
        _lifecycle(repo, g, script)
        result = sprint(repo, env, "start")
        assert result.returncode == 2 and str(child.pid) in result.stderr
        assert "slate review" in result.stderr
        assert not sentinel.exists()
        assert marker.exists() and findings.exists()
        assert not (root / "sprint_branch").exists()
    finally:
        _stop(child)


def test_dry_run_keeps_marker(tmp_path):
    repo, env, _g, root, marker, findings, _log = _open_fixture(tmp_path)
    assert sprint(repo, env, "start", "--dry-run").returncode == 0
    assert marker.exists() and findings.exists()
    assert not (root / "sprint_branch").exists()


def test_red_hook_keeps_marker(tmp_path):
    repo, env, g, root, marker, findings, _log = _open_fixture(tmp_path)
    script = tmp_path / "red.py"
    script.write_text("raise SystemExit(1)\n")
    _lifecycle(repo, g, script)
    assert sprint(repo, env, "start").returncode == 2
    assert marker.exists() and findings.exists()
    assert not (root / "sprint_branch").exists()


def test_hook_started_review_refuses_retirement(tmp_path):
    child = _sleeping()
    try:
        repo, env, g, root, marker, findings, _log = _open_fixture(tmp_path)
        script = tmp_path / "hook.py"
        script.write_text(
            "import json\nfrom pathlib import Path\n"
            f"p = Path({str(marker)!r})\n"
            f"p.write_text(json.dumps(json.loads(p.read_text()) | {{'pid': {child.pid}}}))\n"
        )
        _lifecycle(repo, g, script)
        result = sprint(repo, env, "start")
        assert result.returncode == 2 and str(child.pid) in result.stderr
        assert marker.exists() and findings.exists()
        assert not (root / "sprint_branch").exists()
    finally:
        _stop(child)
