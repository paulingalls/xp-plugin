"""Plan artifacts survive replacement; only explicit amendments buy new planning."""

import json

import pytest
from completed_executor_support import completed, roles
from plan_confirmation_support import amend, consumer, events
from plan_review_install import installed_launch


def test_amendment_preserves_prior_plan_and_findings(tmp_path):
    launch = installed_launch(tmp_path)
    repo, env, seen = completed(tmp_path, launch)
    plans = tmp_path / "data/plans"
    old = [(plans / name).read_bytes() for name in ("story-042.plan.md", "story-042.round-1.md")]
    amend(tmp_path, repo, env, launch)
    count = len(events(seen))
    result = launch(repo, env, "resume", "story-042")
    assert result.returncode == 0, result.stderr
    state = json.loads((plans / "story-042.handoff.json").read_text())
    first = plans / "story-042.predecessors/attempt-1"
    assert state["predecessors"] == [str(first)]
    assert (first / "story-042.plan.md").read_bytes() == old[0]
    assert (first / "story-042.round-1.md").read_bytes() == old[1]
    preserved = [
        path.read_bytes()
        for path in (plans / "story-042.predecessors").rglob("*")
        if path.is_file()
    ]
    assert all(body in preserved for body in old)
    assert roles(seen)[count:] == ["planner", "plan-reviewer", "teammate", "reviewer"]


@pytest.mark.parametrize("artifact", ["receipt", "candidate", "plan", "findings"])
def test_missing_authoritative_binding_refuses_without_launch(tmp_path, artifact):
    launch = installed_launch(tmp_path)
    repo, env, seen = completed(tmp_path, launch)
    plans = tmp_path / "data/plans"
    paths = {
        "receipt": "story-042.round-1.acceptance.json",
        "candidate": "story-042.round-1.card.md",
        "plan": "story-042.plan.md",
        "findings": "story-042.round-1.md",
    }
    (plans / paths[artifact]).unlink()
    count = len(events(seen))
    result = launch(repo, env, "resume", "story-042")
    assert result.returncode == 2, result.stderr
    assert roles(seen)[count:] == []


def test_reason_only_amendment_does_not_waive_question(tmp_path):
    launch = installed_launch(tmp_path)
    repo, env, seen = consumer(tmp_path)
    first = launch(repo, env, "story-042")
    assert first.returncode == 2
    assert (
        launch(repo, env, "amend", "story-042", "--reason", "still needs a human answer").returncode
        == 0
    )
    result = launch(repo, env, "resume", "story-042")
    assert result.returncode == 2
    assert "teammate" not in roles(seen)


@pytest.mark.parametrize("route", ["amendment", "legacy"])
@pytest.mark.parametrize("mutant", [False, pytest.param(True, marks=pytest.mark.meta)])
def test_failed_predecessor_preservation_stops_without_launch(tmp_path, route, mutant):
    from plan_review_install import legacy_credential

    mutation = (
        (
            "except (OSError, ValueError) as error:\n                return stop(\n"
            '                    f"cannot preserve predecessor:',
            "except ZeroDivisionError as error:\n                return stop(\n"
            '                    f"cannot preserve predecessor:',
        )
        if mutant
        else None
    )
    launch = installed_launch(tmp_path, mutation, "scripts/spawn/execution.py")
    repo, env, seen = completed(tmp_path, launch)
    plans = tmp_path / "data/plans"
    saved = (plans / "story-042.plan.md").read_bytes()
    if route == "amendment":
        amend(tmp_path, repo, env, launch)
    else:
        legacy_credential(tmp_path)
    (plans / "story-042.predecessors").write_text("snapshot destination unavailable")
    count = len(events(seen))
    result = launch(repo, env, "resume", "story-042")

    def guarantee():
        assert result.returncode == 2, result.stderr
        assert "cannot preserve predecessor" in result.stderr
        assert "Traceback" not in result.stderr
        assert roles(seen)[count:] == []
        assert (plans / "story-042.plan.md").read_bytes() == saved
        state = json.loads((plans / "story-042.handoff.json").read_text())
        assert state["state"] == "STOPPED"
        (plans / "story-042.predecessors").unlink()
        recovered = launch(repo, env, "resume", "story-042")
        assert recovered.returncode == 0, recovered.stderr

    if mutant:
        with pytest.raises(AssertionError):
            guarantee()
    else:
        guarantee()


@pytest.mark.parametrize("boundary", ["copy", "rename"])
def test_interrupted_predecessor_copy_retries_without_overwrite(tmp_path, boundary):
    import os
    import signal
    import subprocess
    import sys
    import time

    launch = installed_launch(tmp_path)
    repo, env, seen = completed(tmp_path, launch)
    plans = tmp_path / "data/plans"
    saved = {
        p.name: p.read_bytes()
        for p in plans.glob("story-042.*")
        if p.is_file() and "handoff" not in p.name
    }
    amend(tmp_path, repo, env, launch)
    source = tmp_path / "cache/xp-plugin/fixture/scripts/plan_confirmation.py"
    original = source.read_text()
    ready = tmp_path / "copy-started"
    event = (
        "                shutil.copyfileobj(source, destination)"
        if boundary == "copy"
        else "    target.rename(completed)"
    )
    indent = "                " if boundary == "copy" else "    "
    source.write_text(
        original.replace(
            event,
            event + f"\n{indent}Path({str(ready)!r}).touch()\n{indent}__import__('time').sleep(90)",
        )
    )
    count = len(events(seen))
    process = subprocess.Popen(
        [sys.executable, str(source.parent / "spawn.py"), "resume", "story-042"],
        cwd=repo,
        env=env | {"XP_SPAWN_TEST": "1"},
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    try:
        deadline = time.monotonic() + 30
        while not ready.exists() and time.monotonic() < deadline:
            assert process.poll() is None
            time.sleep(0.02)
        assert ready.exists(), "copy event was not reached"
        os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=5)
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=5)
        source.write_text(original)
    assert roles(seen)[count:] == []
    assert {name: (plans / name).read_bytes() for name in saved} == saved
    archive = plans / "story-042.predecessors"
    first = archive / ("attempt-1.copying" if boundary == "copy" else "attempt-1")
    assert first.is_dir()
    retained = {p.name: p.read_bytes() for p in first.iterdir()}
    result = launch(repo, env, "resume", "story-042")
    assert result.returncode == 0, result.stderr
    assert {p.name: p.read_bytes() for p in first.iterdir()} == retained
    retry = archive / "attempt-2"
    assert retry.is_dir()
    assert {name: (retry / name).read_bytes() for name in saved} == saved
    completed_bytes = {p.name: p.read_bytes() for p in retry.iterdir()}
    amend(tmp_path, repo, env, launch)
    assert launch(repo, env, "resume", "story-042").returncode == 0
    assert {p.name: p.read_bytes() for p in retry.iterdir()} == completed_bytes


@pytest.mark.parametrize("mutant", [False, pytest.param(True, marks=pytest.mark.meta)])
def test_unreadable_predecessor_stops_replacement(tmp_path, mutant):
    mutation = (
        ("                shutil.copyfileobj(source, destination)", "                pass")
        if mutant
        else None
    )
    launch = installed_launch(tmp_path, mutation, "scripts/plan_confirmation.py")
    repo, env, seen = completed(tmp_path, launch)
    amend(tmp_path, repo, env, launch)
    trap = tmp_path / "trap"
    trap.mkdir()
    (trap / "sitecustomize.py").write_text(
        "import shutil\ndef deny(*a, **k):\n"
        "    raise PermissionError('constructed copy failure')\nshutil.copyfileobj = deny\n"
    )
    count = len(events(seen))
    plan = tmp_path / "data/plans/story-042.plan.md"
    saved = plan.read_bytes()
    result = launch(repo, env | {"PYTHONPATH": str(trap)}, "resume", "story-042")

    def guarantee():
        assert result.returncode == 2, result.stderr
        assert "constructed copy failure" in result.stderr
        assert roles(seen)[count:] == []
        assert plan.read_bytes() == saved
        assert launch(repo, env, "resume", "story-042").returncode == 0

    if mutant:
        with pytest.raises(AssertionError):
            guarantee()
    else:
        guarantee()


@pytest.mark.meta
@pytest.mark.parametrize("fault", ["partial", "overwrite", "retry"])
def test_predecessor_copy_guard_faults(tmp_path, monkeypatch, fault):
    import test_plan_confirmation as checks
    from plan_review_install import installed_launch as install

    control = tmp_path / "control"
    control.mkdir()
    checks.test_interrupted_predecessor_copy_retries_without_overwrite(control, "rename")
    if fault == "partial":
        mutation = (
            "                shutil.copyfileobj(source, destination)",
            "                pass",
        )
    elif fault == "overwrite":
        mutation = (
            "    target.rename(completed)",
            "    if completed.exists():\n        shutil.rmtree(completed)\n"
            "    target.rename(completed)",
        )
    else:
        mutation = ("    target.mkdir()", "    target.mkdir(exist_ok=True)")

    def launch(root):
        run = install(root, mutation, "scripts/plan_confirmation.py")
        if fault in ("overwrite", "retry"):
            path = root / "cache/xp-plugin/fixture/scripts/plan_confirmation.py"
            text = path.read_text()
            begin = text.index("    while (archive /")
            end = text.index("    target =", begin)
            text = text[:begin] + text[end:]
            if fault == "retry":
                text = text.replace('f"attempt-{number}.copying"', '"attempt-1.copying"')
            path.write_text(text)
        return run

    monkeypatch.setattr(checks, "installed_launch", launch)
    mutant = tmp_path / "mutant"
    mutant.mkdir()
    with pytest.raises(AssertionError):
        checks.test_interrupted_predecessor_copy_retries_without_overwrite(mutant, "rename")
