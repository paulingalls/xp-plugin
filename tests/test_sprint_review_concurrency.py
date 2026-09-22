"""Concurrent sprint review stages preserve the recorded prefix."""

import json
import subprocess
import sys
import time

from close_helpers import launches
from spawn_helpers import stub_codex
from sprint_helpers import (
    CLOSE,
    CONFIG,
    head,
    make_repo,
    marker_path,
    sprint,
    stage_key,
    staged_stub,
)


def test_every_finder_starts_before_any_finishes_and_records_declared_order(tmp_path):
    repo, env, _git = make_repo(tmp_path)
    staged_stub(tmp_path)
    stub = tmp_path / "bin" / "claude"
    stub.write_text(
        stub.read_text().replace(
            "open(m.group(1).strip(), 'w').write(json.dumps(report))\n",
            "if key == 'close': sys.exit(1)\n"
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
    finders = ("find-security", "find-state-lifecycle", "find-test-vacuity")
    try:
        deadline = time.monotonic() + 15
        started = [tmp_path / f"{name}.started" for name in finders]
        while time.monotonic() < deadline and not all(p.exists() for p in started):
            time.sleep(0.02)
        assert all(p.exists() for p in started), "every finder did not start at once"
        for name in reversed(finders):
            (tmp_path / f"{name}.release").touch()
            report = tmp_path / "data/reports/sprint" / f"2.{name}.round-1.json"
            while time.monotonic() < deadline and not report.exists():
                time.sleep(0.02)
        out, err = proc.communicate(timeout=15)
        assert proc.returncode == 2 and "reviewer exited 1" in err, out + err
        record = json.loads(marker_path(tmp_path).read_text())["rounds"][0]
        assert record["stages"] == list(finders)
        assert len(launches(tmp_path)) == 4
        assert record["reviewed_head"] == head(repo, env)
    finally:
        for name in finders:
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
    assert {stage_key(item["stdin"]) for item in launches(tmp_path)[count:]} >= {
        "find-state-lifecycle",
        "find-test-vacuity",
    }


def test_a_finder_commit_is_refused_after_its_concurrent_batch(tmp_path):
    repo, env, _git = make_repo(tmp_path)
    staged_stub(tmp_path)
    stub = tmp_path / "bin" / "claude"
    stub.write_text(
        stub.read_text().replace(
            "open(m.group(1).strip(), 'w').write(json.dumps(report))\n",
            "if key == 'find-test-vacuity':\n"
            "    os.system('echo X >> src.py && git commit -qam snuck')\n"
            "open(m.group(1).strip(), 'w').write(json.dumps(report))\n",
        )
    )
    result = sprint(repo, env, "review")
    assert result.returncode == 2 and "read-only reviewer changed HEAD" in result.stderr
    record = json.loads(marker_path(tmp_path).read_text())["rounds"][0]
    assert record["stages"] == ["find-security", "find-state-lifecycle", "find-test-vacuity"]
    assert "close" not in [stage_key(item["stdin"]) for item in launches(tmp_path)]


def test_verifiers_start_after_finders_and_closer_waits_for_both(tmp_path):
    config = CONFIG + "review:\n  verify_batches: 2\n"
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
        assert "close" not in [stage_key(item["stdin"]) for item in launches(tmp_path)]
        (tmp_path / "verify-2.release").touch()
        report = tmp_path / "data/reports/sprint/2.verify-2.round-1.json"
        while time.monotonic() < deadline and not report.exists():
            time.sleep(0.02)
        time.sleep(0.5)
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


def test_codex_finders_start_together_in_one_checkout(tmp_path):
    config = (
        CONFIG.replace(
            "  reviewer: claude/opus\n",
            "  reviewer: claude/opus\n  finder: codex/gpt-6-sol/medium\n",
        )
        + "codex_sandbox: danger-full-access\n"
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
    finders = ("find-security", "find-state-lifecycle", "find-test-vacuity")
    try:
        deadline = time.monotonic() + 15
        started = [tmp_path / f"{name}.started" for name in finders]
        while time.monotonic() < deadline and not all(p.exists() for p in started):
            time.sleep(0.02)
        assert all(p.exists() for p in started), "every Codex finder did not start at once"
        for name in finders:
            (tmp_path / f"{name}.release").touch()
        out, err = proc.communicate(timeout=15)
        assert proc.returncode == 0, out + err
        assert "incomplete" not in json.loads(marker_path(tmp_path).read_text())["rounds"][0]
    finally:
        for name in finders:
            (tmp_path / f"{name}.release").touch()
        if proc.poll() is None:
            proc.kill()
            proc.communicate()
