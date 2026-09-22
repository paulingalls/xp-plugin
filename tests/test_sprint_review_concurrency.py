"""Concurrent sprint review stages preserve the recorded prefix."""

import json
import subprocess
import sys
import time

import pytest
from close_helpers import launches
from spawn_helpers import stub_codex
from sprint_helpers import CLOSE, CONFIG, head, make_repo, marker_path, sprint, staged_stub


@pytest.mark.parametrize("config", [CONFIG, CONFIG + "review:\n  concurrent_legs: 2\n"])
def test_two_finders_start_before_either_finishes_and_record_declared_order(tmp_path, config):
    repo, env, _git = make_repo(tmp_path, config=config)
    staged_stub(tmp_path)
    stub = tmp_path / "bin" / "claude"
    stub.write_text(
        stub.read_text().replace(
            "open(m.group(1).strip(), 'w').write(json.dumps(report))\n",
            "if key.startswith('find-'):\n"
            "    open(os.path.join(os.environ['HOME'], key + '.started'), 'w').close()\n"
            "    import time\n"
            "    while not os.path.exists(os.path.join(os.environ['HOME'], key + '.release')):\n"
            "        time.sleep(.02)\n"
            "open(m.group(1).strip(), 'w').write(json.dumps(report))\n",
        )
    )
    proc = subprocess.Popen(
        [sys.executable, str(CLOSE), "sprint", "2", "review"],
        cwd=repo,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        deadline = time.monotonic() + 15
        first = tmp_path / "find-security.started"
        second = tmp_path / "find-state-lifecycle.started"
        third = tmp_path / "find-test-vacuity.started"
        while time.monotonic() < deadline and not (first.exists() and second.exists()):
            time.sleep(0.02)
        assert first.exists() and second.exists(), "two finders did not start"
        assert not third.exists(), "configured bound was exceeded"
        (tmp_path / "find-state-lifecycle.release").touch()
        while time.monotonic() < deadline and not third.exists():
            time.sleep(0.02)
        assert third.exists(), "third finder did not start after a slot freed"
        (tmp_path / "find-test-vacuity.release").touch()
        (tmp_path / "find-security.release").touch()
        out, err = proc.communicate(timeout=15)
        assert proc.returncode == 0, out + err
        record = json.loads(marker_path(tmp_path).read_text())["rounds"][0]
        assert "incomplete" not in record
        assert len(launches(tmp_path)) == 4
        assert record["reviewed_head"] == head(repo, env)
    finally:
        for name in ("find-security", "find-state-lifecycle", "find-test-vacuity"):
            (tmp_path / f"{name}.release").touch()
        if proc.poll() is None:
            proc.kill()
            proc.communicate()


def test_failed_finder_keeps_completed_siblings_and_reruns_the_post_gap_report(tmp_path):
    repo, env, _git = make_repo(tmp_path)
    staged_stub(
        tmp_path,
        find_security={"fixed": [], "blocking": ["security issue"], "noted": []},
        find_test_vacuity={"fixed": [], "blocking": ["test issue"], "noted": []},
    )
    stub = tmp_path / "bin" / "claude"
    failure = "if key == 'find-state-lifecycle': sys.exit(1)\n"
    stub.write_text(
        stub.read_text().replace(
            "open(m.group(1).strip(), 'w').write(json.dumps(report))\n",
            failure + "open(m.group(1).strip(), 'w').write(json.dumps(report))\n",
        )
    )
    first = sprint(repo, env, "review")
    assert first.returncode == 2 and "reviewer exited 1" in first.stderr
    saved = json.loads(marker_path(tmp_path).read_text())["rounds"][0]
    assert saved["stages"] == ["find-security", "find-test-vacuity"]
    assert saved["blocking"] == ["security issue", "test issue"]
    later = tmp_path / "data/reports/sprint/2.find-test-vacuity.round-1.json"
    assert later.exists()
    assert json.loads(later.read_text())["blocking"] == ["test issue"]
    stub.write_text(stub.read_text().replace(failure, ""))
    count = len(launches(tmp_path))
    second = sprint(repo, env, "review")
    assert second.returncode == 0, second.stderr
    resumed = json.loads(marker_path(tmp_path).read_text())["rounds"][0]
    assert resumed["reused"] == ["find-security"]
    assert resumed["ran"][:2] == ["find-state-lifecycle", "find-test-vacuity"]
    from sprint_helpers import stage_key

    assert {stage_key(item["stdin"]) for item in launches(tmp_path)[count:]} >= {
        "find-state-lifecycle",
        "find-test-vacuity",
    }


@pytest.mark.parametrize("value", ["0", "-1", "many", ""])
def test_invalid_concurrency_bound_refuses_before_any_launch(tmp_path, value):
    repo, env, _git = make_repo(tmp_path, config=CONFIG + f"review:\n  concurrent_legs: {value}\n")
    result = sprint(repo, env, "review")
    assert result.returncode == 2 and "review.concurrent_legs" in result.stderr
    assert launches(tmp_path) == []


def test_verifiers_start_after_finders_and_closer_waits_for_both(tmp_path):
    config = CONFIG + "review:\n  concurrent_legs: 2\n  verify_batches: 2\n"
    repo, env, _git = make_repo(tmp_path, config=config)
    staged_stub(tmp_path, find={"fixed": [], "blocking": ["one", "two"], "noted": []})
    stub = tmp_path / "bin" / "claude"
    stub.write_text(
        stub.read_text().replace(
            "open(m.group(1).strip(), 'w').write(json.dumps(report))\n",
            "if key.startswith('verify-'):\n"
            "    open(os.path.join(os.environ['HOME'], key + '.started'), 'w').close()\n"
            "    import time\n"
            "    while not os.path.exists(os.path.join(os.environ['HOME'], key + '.release')):\n"
            "        time.sleep(.02)\n"
            "open(m.group(1).strip(), 'w').write(json.dumps(report))\n",
        )
    )
    proc = subprocess.Popen(
        [sys.executable, str(CLOSE), "sprint", "2", "review"],
        cwd=repo,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline and not all(
            (tmp_path / f"verify-{n}.started").exists() for n in (1, 2)
        ):
            time.sleep(0.02)
        assert all((tmp_path / f"verify-{n}.started").exists() for n in (1, 2))
        assert all(
            (tmp_path / "data/reports/sprint" / f"2.find-{name}.round-1.json").exists()
            for name in ("security", "state-lifecycle", "test-vacuity")
        )
        from sprint_helpers import stage_key

        assert "close" not in [stage_key(item["stdin"]) for item in launches(tmp_path)]
        (tmp_path / "verify-2.release").touch()
        assert "close" not in [stage_key(item["stdin"]) for item in launches(tmp_path)]
        (tmp_path / "verify-1.release").touch()
        out, err = proc.communicate(timeout=15)
        assert proc.returncode == 0, out + err
        assert [stage_key(item["stdin"]) for item in launches(tmp_path)][-1] == "close"
    finally:
        for n in (1, 2):
            (tmp_path / f"verify-{n}.release").touch()
        if proc.poll() is None:
            proc.kill()
            proc.communicate()


def test_codex_finders_share_one_checkout_without_status_lock_failure(tmp_path):
    config = (
        CONFIG.replace(
            "  reviewer: claude/opus\n",
            "  reviewer: claude/opus\n  finder: codex/gpt-6-sol/medium\n",
        )
        + "codex_sandbox: danger-full-access\nreview:\n  concurrent_legs: 2\n"
    )
    repo, env, _git = make_repo(tmp_path, config=config)
    stub_codex(tmp_path, commit=False, sandbox="danger-full-access")
    codex = tmp_path / "bin" / "codex"
    codex.write_text(
        codex.read_text().replace(
            " open(m.group(1).strip(), 'w').write(",
            " key = os.path.basename(m.group(1).strip()).split('.')[1]\n"
            " open(os.path.join(os.environ['HOME'], key + '.started'), 'w').close()\n"
            " import time\n"
            " while not os.path.exists(os.path.join(os.environ['HOME'], key + '.release')):\n"
            "  time.sleep(.02)\n"
            " subprocess.run(['git', 'status', '--porcelain'], check=True, capture_output=True)\n"
            " open(m.group(1).strip(), 'w').write(",
        )
    )
    proc = subprocess.Popen(
        [sys.executable, str(CLOSE), "sprint", "2", "review"],
        cwd=repo,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        deadline = time.monotonic() + 15
        first = tmp_path / "find-security.started"
        second = tmp_path / "find-state-lifecycle.started"
        while time.monotonic() < deadline and not (first.exists() and second.exists()):
            time.sleep(0.02)
        assert first.exists() and second.exists(), "two Codex finders did not start"
        for name in ("find-security", "find-state-lifecycle", "find-test-vacuity"):
            (tmp_path / f"{name}.release").touch()
        out, err = proc.communicate(timeout=15)
        assert proc.returncode == 0, out + err
        assert "incomplete" not in json.loads(marker_path(tmp_path).read_text())["rounds"][0]
    finally:
        for name in ("find-security", "find-state-lifecycle", "find-test-vacuity"):
            (tmp_path / f"{name}.release").touch()
        if proc.poll() is None:
            proc.kill()
            proc.communicate()
