"""Readiness-synchronized child kills with work and log preservation."""

from plan_confirmation_support import consumer, events


def interrupted_stage(tmp_path, launch, boundary="story-tier"):
    import os
    import signal
    import subprocess
    import sys
    import time

    repo, env, seen = consumer(tmp_path, initial_status="clean", initial_question=None)
    (tmp_path / "executor-stop").unlink()
    ready = tmp_path / "tier-ready"
    release = tmp_path / "tier-release"
    tier = tmp_path / "tier.py"
    tier.write_text(
        "from pathlib import Path\nimport time\n"
        f"Path({str(ready)!r}).touch()\n"
        f"while not Path({str(release)!r}).exists(): time.sleep(.05)\n"
    )
    if boundary == "executor":
        binary = tmp_path / "bin/claude"
        pause = (
            " if not os.path.exists(" + repr(str(release)) + "):\n"
            "  import time\n"
            "  open('src/one.py', 'w').write('STAGED = True\\n')\n"
            "  subprocess.run(['git', 'add', 'src/one.py'], check=True)\n"
            "  open('src/thing.py', 'a').write('# UNSTAGED-SENTINEL\\n')\n"
            "  open('src/two.py', 'w').write('UNTRACKED = True\\n')\n"
            "  open(" + repr(str(ready)) + ", 'w').write(str(os.getpid()))\n"
            "  while not os.path.exists(" + repr(str(release)) + "): time.sleep(.05)\n"
        )
        binary.write_text(
            binary.read_text().replace(
                "elif role == 'reviewer':", pause + "elif role == 'reviewer':"
            )
        )
    config = repo / ".xp/config.yml"
    config.write_text(config.read_text().replace("story: true", f"story: {sys.executable} {tier}"))
    subprocess.run(["git", "commit", "-am", "controlled tier"], cwd=repo, env=env, check=True)
    subprocess.run(["git", "branch", "-f", "main", "HEAD"], cwd=repo, env=env, check=True)
    script = tmp_path / "cache/xp-plugin/fixture/scripts/spawn.py"
    with (tmp_path / "killed.log").open("w") as log:
        proc = subprocess.Popen(
            [sys.executable, str(script), "story-042"],
            cwd=repo,
            env=env | {"XP_SPAWN_TEST": "1"},
            stdout=log,
            stderr=log,
            start_new_session=True,
        )
        try:
            deadline = time.monotonic() + 30
            while not ready.exists() and proc.poll() is None and time.monotonic() < deadline:
                time.sleep(0.05)
            assert ready.exists(), (tmp_path / "killed.log").read_text()
            if boundary == "executor":
                os.kill(int(ready.read_text()), signal.SIGKILL)
            else:
                os.killpg(proc.pid, signal.SIGKILL)
            proc.wait(timeout=30)
        finally:
            if proc.poll() is None:
                os.killpg(proc.pid, signal.SIGKILL)
                proc.wait(timeout=10)
    tree = tmp_path / "data/worktrees/story-042"
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=tree, text=True)
    plan = tmp_path / "data/plans/story-042.plan.md"
    prior_plan = plan.read_bytes()
    if boundary == "executor":
        status = subprocess.check_output(["git", "status", "--porcelain"], cwd=tree, text=True)
        assert (
            "A  src/one.py" in status and " M src/thing.py" in status and "?? src/two.py" in status
        )
    executor_log = tmp_path / "data/logs/story-042-executor.log"
    prior_log = executor_log.read_bytes()
    release.touch()
    before = len(events(seen))
    result = launch(repo, env, "resume", "story-042")
    assert result.returncode == 0, result.stderr
    added = [event["role"] for event in events(seen)][before:]
    assert added == (["teammate", "reviewer"] if boundary == "executor" else ["reviewer"]), added
    if boundary == "story-tier":
        assert subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=tree, text=True) == head
    else:
        assert (tree / "src/one.py").read_text() == "STAGED = True\n"
        assert (tree / "src/two.py").read_text() == "UNTRACKED = True\n"
        assert "UNSTAGED-SENTINEL" in (tree / "src/thing.py").read_text()
    if boundary == "executor":
        import gzip

        assert gzip.decompress(executor_log.with_suffix(".log.1.gz").read_bytes()) == prior_log
    else:
        assert executor_log.read_bytes() == prior_log
    assert plan.read_bytes() == prior_plan
