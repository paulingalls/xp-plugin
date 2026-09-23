"""A card edit stops only the review that launched against that card."""

import contextlib
import os
import signal
import subprocess
import sys
import time

import pytest
from close_helpers import CLOSE, close, make_repo, stub_reviewer

SCRIPTS = CLOSE.parent


def sleeping_reviewer(tmp_path):
    script = tmp_path / "bin" / "claude"
    script.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, pathlib, re, subprocess, sys, time\n"
        "if sys.argv[1:] == ['plugin', 'list', '--json']:\n"
        ' print(\'[{"id":"xp-plugin@xp-plugin","version":"fixture",'
        '"scope":"user"}]\'); sys.exit()\n'
        "prompt = sys.stdin.read()\n"
        f"root = pathlib.Path({str(tmp_path)!r})\n"
        "report = pathlib.Path(re.search(r'^REPORT_PATH: (.+)$', prompt, re.M).group(1))\n"
        "report.write_text(json.dumps({'fixed': [], 'blocking': [], 'noted': []}))\n"
        "patch = re.search(r'^PATCH_PATH: (.+)$', prompt, re.M)\n"
        "if patch: pathlib.Path(patch.group(1)).write_text('')\n"
        "mode = root.joinpath('mode').read_text() if root.joinpath('mode').exists() else ''\n"
        "if mode == 'dirty': root.joinpath('repo', 'dirty.txt').write_text('dirty\\n')\n"
        "if mode == 'moved':\n"
        " target = root.joinpath('repo', 'moved.txt'); target.write_text('moved\\n')\n"
        " subprocess.run(['git', 'add', 'moved.txt'], check=True)\n"
        " subprocess.run(['git', '-c', 'user.name=lead', '-c', 'user.email=lead@x',"
        " 'commit', '-qm', 'lead moved HEAD'], check=True)\n"
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'])\n"
        "root.joinpath('pid').write_text(str(os.getpid()))\n"
        "root.joinpath('started').write_text('yes')\n"
        "for _ in range(1200):\n"
        " if root.joinpath('release').exists(): break\n"
        " time.sleep(0.1)\n"
        "else: sys.exit(3)\n"
        "child.terminate(); child.wait()\n"
        "print(json.dumps({'type':'system','subtype':'init','session_id':'stub'}))\n"
        "print(json.dumps({'type':'result','subtype':'success','is_error':False,'result':'done'}))\n"
    )
    script.chmod(0o755)


def stop_stuck(proc, tmp_path):
    if proc.poll() is None:
        pid = tmp_path / "pid"
        if pid.exists():
            with contextlib.suppress(ProcessLookupError):
                os.killpg(int(pid.read_text()), signal.SIGKILL)
        proc.kill()
        proc.communicate(timeout=2)


def test_card_edit_cancels_running_review(tmp_path):
    repo, env, _g = make_repo(tmp_path)
    sleeping_reviewer(tmp_path)
    proc = subprocess.Popen(
        [sys.executable, str(CLOSE), "story", "story-042", "review"],
        cwd=repo,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        end = time.monotonic() + 10
        while not (tmp_path / "started").exists() and time.monotonic() < end:
            time.sleep(0.05)
        assert (tmp_path / "started").exists(), "reviewer never started"
        plan = tmp_path / "data" / "plan.md"
        plan.write_text(plan.read_text().replace("Context: demo.", "Context: edited."))
        out, err = proc.communicate(timeout=10)
    finally:
        stop_stuck(proc, tmp_path)
    assert proc.returncode == 2, (out, err)
    assert "CANCELLED" in err and "card" in err, err
    assert "NO OUTPUT" not in err and "XP_AGENT_TIMEOUT" not in err
    assert not (tmp_path / "data" / "markers" / "story-042.review-launch").exists()
    assert not (tmp_path / "data" / "markers" / "story-042.close.json").exists()
    assert list((tmp_path / "data" / "reports").glob("*CANCELLED*.json"))
    assert list((tmp_path / "data" / "reports").glob("*CANCELLED*.patch"))
    assert list((tmp_path / "data" / "logs").glob("*CANCELLED*.log"))
    landed = close(repo, env, "land")
    assert "unrecorded review" not in landed.stderr
    cancelled = list((tmp_path / "data" / "reports").glob("*CANCELLED*.json"))
    saved = cancelled[0].read_text()
    plan.write_text(plan.read_text().replace("Context: edited.", "Context: demo."))
    stub_reviewer(tmp_path)
    later = close(repo, env, "review")
    assert later.returncode == 0, later.stderr
    assert cancelled[0].read_text() == saved


def test_unchanged_card_records_round(tmp_path):
    repo, env, _g = make_repo(tmp_path)
    sleeping_reviewer(tmp_path)
    proc = subprocess.Popen(
        [sys.executable, str(CLOSE), "story", "story-042", "review"],
        cwd=repo,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        end = time.monotonic() + 10
        while not (tmp_path / "started").exists() and time.monotonic() < end:
            time.sleep(0.05)
        assert (tmp_path / "started").exists()
        (tmp_path / "release").write_text("go")
        out, err = proc.communicate(timeout=10)
    finally:
        stop_stuck(proc, tmp_path)
    assert proc.returncode == 0, (out, err)
    state = __import__("json").loads(
        (tmp_path / "data" / "markers" / "story-042.close.json").read_text()
    )
    assert len(state["rounds"]) == 1


def test_sibling_card_edit_does_not_cancel(tmp_path):
    repo, env, _g = make_repo(tmp_path)
    plan = tmp_path / "data" / "plan.md"
    plan.write_text(plan.read_text() + "\n#### story-099 — sibling   [planned]\nContext: first\n")
    sleeping_reviewer(tmp_path)
    proc = subprocess.Popen(
        [sys.executable, str(CLOSE), "story", "story-042", "review"],
        cwd=repo,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        end = time.monotonic() + 10
        while not (tmp_path / "started").exists() and time.monotonic() < end:
            time.sleep(0.05)
        assert (tmp_path / "started").exists()
        plan.write_text(plan.read_text().replace("Context: first", "Context: second"))
        time.sleep(0.5)
        assert proc.poll() is None
        (tmp_path / "release").write_text("go")
        out, err = proc.communicate(timeout=10)
    finally:
        stop_stuck(proc, tmp_path)
    assert proc.returncode == 0, (out, err)


@pytest.mark.parametrize("name", ["plan-reviewer", "planner"])
def test_other_review_roles_keep_running_when_card_changes(tmp_path, name):
    repo, env, _g = make_repo(tmp_path)
    (repo / ".xp" / "config.yml").write_text(
        "roles:\n  reviewer: claude/opus\n  executor: claude/opus\ntests:\n  story: true\n"
    )
    sleeping_reviewer(tmp_path)
    report = tmp_path / "data" / "reports" / "direct.json"
    report.parent.mkdir(exist_ok=True)
    prompt = f"REPORT_PATH: {report}\n"
    code = (
        "import review, sys; from pathlib import Path; "
        "print(review.run(sys.argv[1], Path.cwd(), name=sys.argv[2], card=sys.argv[3]))"
    )
    plan = tmp_path / "data" / "plan.md"
    env = env | {"PYTHONPATH": str(SCRIPTS)}
    proc = subprocess.Popen(
        [sys.executable, "-c", code, prompt, name, plan.read_text()],
        cwd=repo,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        end = time.monotonic() + 10
        while not (tmp_path / "started").exists() and time.monotonic() < end:
            time.sleep(0.05)
        assert (tmp_path / "started").exists(), "role never started"
        plan.write_text(plan.read_text().replace("Context: demo.", "Context: edited."))
        time.sleep(0.5)
        assert proc.poll() is None
        (tmp_path / "release").write_text("go")
        out, err = proc.communicate(timeout=10)
    finally:
        stop_stuck(proc, tmp_path)
    assert proc.returncode == 0 and "done" in out, (out, err)


@pytest.mark.parametrize("change_after_restore", [False, True])
def test_unreadable_card_does_not_kill_watcher(tmp_path, change_after_restore):
    repo, env, _g = make_repo(tmp_path)
    sleeping_reviewer(tmp_path)
    proc = subprocess.Popen(
        [sys.executable, str(CLOSE), "story", "story-042", "review"],
        cwd=repo,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        end = time.monotonic() + 10
        while not (tmp_path / "started").exists() and time.monotonic() < end:
            time.sleep(0.05)
        assert (tmp_path / "started").exists()
        plan = tmp_path / "data" / "plan.md"
        original = plan.read_bytes()
        plan.write_bytes(b"\xff")
        time.sleep(0.8)
        assert proc.poll() is None
        plan.write_bytes(original)
        if change_after_restore:
            plan.write_text(plan.read_text().replace("Context: demo.", "Context: changed."))
        else:
            (tmp_path / "release").write_text("go")
        out, err = proc.communicate(timeout=10)
    finally:
        stop_stuck(proc, tmp_path)
    if change_after_restore:
        assert proc.returncode == 2 and "CANCELLED" in err, (out, err)
    else:
        assert proc.returncode == 0, (out, err)


def test_dirty_cancel_keeps_launch_marker(tmp_path):
    repo, env, _g = make_repo(tmp_path)
    (tmp_path / "mode").write_text("dirty")
    sleeping_reviewer(tmp_path)
    proc = subprocess.Popen(
        [sys.executable, str(CLOSE), "story", "story-042", "review"],
        cwd=repo,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        end = time.monotonic() + 10
        while not (tmp_path / "started").exists() and time.monotonic() < end:
            time.sleep(0.05)
        assert (tmp_path / "started").exists()
        plan = tmp_path / "data" / "plan.md"
        plan.write_text(plan.read_text().replace("Context: demo.", "Context: changed."))
        out, err = proc.communicate(timeout=10)
    finally:
        stop_stuck(proc, tmp_path)
    assert proc.returncode == 2 and "dirty.txt" in err, (out, err)
    assert "reset --hard" not in err
    assert (tmp_path / "data" / "markers" / "story-042.review-launch").exists()
    (repo / "dirty.txt").unlink()
    assert "unrecorded review" in close(repo, env, "land").stderr


def test_close_marker_edit_during_cancel_keeps_launch_marker(tmp_path):
    repo, env, _g = make_repo(tmp_path)
    sleeping_reviewer(tmp_path)
    proc = subprocess.Popen(
        [sys.executable, str(CLOSE), "story", "story-042", "review"],
        cwd=repo,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        end = time.monotonic() + 10
        while not (tmp_path / "started").exists() and time.monotonic() < end:
            time.sleep(0.05)
        assert (tmp_path / "started").exists()
        marker = tmp_path / "data" / "markers" / "story-042.close.json"
        marker.write_text('{"rounds": [], "blocking": ["changed"]}')
        plan = tmp_path / "data" / "plan.md"
        plan.write_text(plan.read_text().replace("Context: demo.", "Context: changed."))
        out, err = proc.communicate(timeout=10)
    finally:
        stop_stuck(proc, tmp_path)
    assert proc.returncode == 2 and "CANCELLED" in err, (out, err)
    assert "close marker changed" in err
    assert (tmp_path / "data" / "markers" / "story-042.review-launch").exists()
    assert "unrecorded review" in close(repo, env, "land").stderr


def test_moved_head_cancel_keeps_launch_marker_without_reset(tmp_path):
    repo, env, _g = make_repo(tmp_path)
    (tmp_path / "mode").write_text("moved")
    sleeping_reviewer(tmp_path)
    proc = subprocess.Popen(
        [sys.executable, str(CLOSE), "story", "story-042", "review"],
        cwd=repo,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        end = time.monotonic() + 10
        while not (tmp_path / "started").exists() and time.monotonic() < end:
            time.sleep(0.05)
        assert (tmp_path / "started").exists()
        plan = tmp_path / "data" / "plan.md"
        plan.write_text(plan.read_text().replace("Context: demo.", "Context: changed."))
        out, err = proc.communicate(timeout=10)
    finally:
        stop_stuck(proc, tmp_path)
    assert proc.returncode == 2, (out, err)
    assert "lead moved HEAD" in err and "reset --hard" not in err, err
    assert (tmp_path / "data" / "markers" / "story-042.review-launch").exists()
    assert "unrecorded review" in close(repo, env, "land").stderr


def test_free_review_inherits_card_cancel(tmp_path):
    from test_close_free import reviewed

    repo, env, _g = reviewed(tmp_path)
    sleeping_reviewer(tmp_path)
    (tmp_path / "started").unlink(missing_ok=True)
    proc = subprocess.Popen(
        [sys.executable, str(CLOSE), "free", "fix-typo", "review"],
        cwd=repo,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        end = time.monotonic() + 10
        while not (tmp_path / "started").exists() and time.monotonic() < end:
            time.sleep(0.05)
        assert (tmp_path / "started").exists(), "free reviewer never started"
        plan = tmp_path / "data" / "plan.md"
        before, free_card = plan.read_text().split("#### free-", 1)
        changed = free_card.replace("Context:", "Context: edited ", 1)
        plan.write_text(before + "#### free-" + changed)
        out, err = proc.communicate(timeout=10)
    finally:
        stop_stuck(proc, tmp_path)
    assert proc.returncode == 2 and "CANCELLED" in err, (out, err)


def test_torn_plan_read_does_not_cancel_until_seen_twice(monkeypatch):
    sys.path.insert(0, str(SCRIPTS / "close"))
    import review_cancel

    reads = iter(["#### story-042 — de", "launch card", "edited", "edited"])
    monkeypatch.setattr(review_cancel, "card_now", lambda _story: next(reads))
    changed = review_cancel.card_changed("story-042", "launch card")

    assert [changed() for _ in range(4)] == [False, False, False, True]
