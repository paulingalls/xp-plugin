import json
import shlex
import subprocess
import sys
from pathlib import Path

import pytest
from session_start_helpers import next_lines, run_recovery, xp_repo
from slate_review_helpers import slate_repo, slate_review, stub_slate_reviewer


def _recovery_fixture(tmp_path, branch=None, pid=99999999):
    repo, _git = xp_repo(tmp_path)
    root = tmp_path / "xp"
    (root / "plan.md").write_text("# plan\n### Sprint 1\n#### story-042 — work   [planned]\n")
    if branch:
        (root / "sprint_branch").write_text(branch + "\n")
    log = root / "logs" / "1-slate-review.log"
    log.parent.mkdir()
    log.write_bytes(b"failed review\n")
    marker = root / "markers" / "1.slate-review-incomplete"
    marker.parent.mkdir()
    marker.write_text(json.dumps({"pid": pid, "log": str(log)}))
    return repo, root, marker, log


def test_dead_open_marker_falls_through_to_card(tmp_path, monkeypatch):
    repo, root, marker, log = _recovery_fixture(tmp_path, "sprint-001")
    monkeypatch.setenv("XP_DATA", str(root))
    from session_start import slate_review_state

    before = marker.read_bytes(), log.read_bytes()
    assert slate_review_state("1") == ("stale-after-open", None)
    recovery = run_recovery(repo, tmp_path)
    assert recovery.returncode == 0, recovery.stderr
    assert next_lines(recovery.stdout) == [
        "NEXT: story-042 is [planned] — run `spawn.py ready story-042`"
    ]
    assert (marker.read_bytes(), log.read_bytes()) == before


def test_live_open_marker_stays_next(tmp_path, monkeypatch):
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        repo, root, _marker, _log = _recovery_fixture(tmp_path, "sprint-001", child.pid)
        monkeypatch.setenv("XP_DATA", str(root))
        from session_start import slate_review_state

        assert slate_review_state("1") == ("running", child.pid)
        assert next_lines(run_recovery(repo, tmp_path).stdout) == [
            f"NEXT: Sprint 1 slate review running (pid {child.pid})"
            " — run `slate_review.py 1` to join it"
        ]
    finally:
        child.terminate()
        child.wait(timeout=5)


@pytest.mark.parametrize("branch", [None, "sprint-002"])
def test_dead_marker_before_this_sprint_opens_stays_next(tmp_path, monkeypatch, branch):
    repo, root, _marker, _log = _recovery_fixture(tmp_path, branch)
    monkeypatch.setenv("XP_DATA", str(root))
    from session_start import slate_review_state

    assert slate_review_state("1") == ("incomplete", None)
    if branch is None:
        assert next_lines(run_recovery(repo, tmp_path).stdout) == [
            "NEXT: Sprint 1 slate review incomplete — run `slate_review.py 1`"
        ]


@pytest.mark.parametrize("open_sprint", [True, False])
def test_capped_slate_refuses_with_correct_action(tmp_path, open_sprint):
    repo, env = slate_repo(tmp_path)
    root = Path(env["XP_DATA"])
    if open_sprint:
        (root / "sprint_branch").write_text("sprint-001\n")
    reviews = root / "slate-reviews"
    reviews.mkdir()
    for number in (1, 2):
        (reviews / f"sprint-1.round-{number}.md").write_text("completed\n")
    marker = root / "markers" / "1.slate-review-incomplete"
    marker.parent.mkdir(exist_ok=True)
    marker.write_text(json.dumps({"pid": 99999999, "findings": str(reviews / "missing.md")}))
    launch = stub_slate_reviewer(tmp_path)

    result = slate_review(repo, env)

    assert result.returncode == 2
    assert not launch.exists() and not (reviews / "sprint-1.round-3.md").exists()
    if open_sprint:
        assert "continue with the cards" in result.stderr
        assert "then open the sprint" not in result.stderr
    else:
        assert "then open the sprint" in result.stderr


@pytest.mark.parametrize(
    "kind,identifier,argv",
    [
        ("slate", "1", ["/current/slate_review.py", "1"]),
        ("plan", "story-042", ["/current/plan_review.py", "story-042", "/plan.md"]),
        ("refresh", "story-042", ["/current/slate_review.py", "story-042", "--refresh"]),
    ],
)
@pytest.mark.parametrize("route", ["rejoin", "new"])
def test_wait_rebuilds_command_from_current_invocation(
    tmp_path, monkeypatch, capsys, kind, identifier, argv, route
):
    import review_runner

    root = tmp_path / "data"
    monkeypatch.setenv("XP_DATA", str(root))
    out = root / "findings.md"
    log = root / "review.log"
    log.parent.mkdir()
    log.write_text("review stopped\n")
    marker = review_runner.review_marker(identifier, kind)
    marker.parent.mkdir()
    stored = f"run python3 /deleted-cache/{kind}.py again to join or restart it"
    marker.write_text(json.dumps({"findings": str(out), "log": str(log), "next": stored}))
    monkeypatch.setattr(review_runner, "_dead", lambda _pid, _child: True)
    monkeypatch.setattr(
        review_runner, "_running", lambda _id, _kind: (out, 99999999) if route == "rejoin" else None
    )
    if route == "new":
        monkeypatch.setattr(review_runner, "_detach", lambda *_args: (99999999, object()))

    assert review_runner.run_detached(identifier, kind, out, argv) == 2
    shown = capsys.readouterr().err
    assert "ended without a verdict" in shown
    assert shlex.join(["python3", *argv]) in shown
    assert "/deleted-cache/" not in shown
    assert json.loads(marker.read_text())["next"] == stored
