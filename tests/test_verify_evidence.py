"""Durable evidence from actual consumer Verify invocations."""

import json
import os
import shlex
import signal
import sys
from contextlib import suppress
from pathlib import Path

import pytest
from close_helpers import CLOSE, make_repo
from close_helpers import close as source_close

TEST_CLOSE = (
    Path(os.environ.get("XP_VERIFY_TEST_PLUGIN", str(CLOSE.parent.parent))) / "scripts/close.py"
)


def close(repo, env, *args):
    return source_close(repo, env, *args, close=TEST_CLOSE)


def command(source):
    return shlex.join([sys.executable, "-c", source])


def evidence(root):
    return sorted((root / "data" / "logs" / "verify").glob("*/run.json"))


def locator(refusal):
    for line in refusal.splitlines():
        if line.startswith("Verify evidence: "):
            return Path(line.removeprefix("Verify evidence: "))
    raise AssertionError(f"no reachable Verify evidence in refusal: {refusal[-3000:]}")


@pytest.mark.parametrize("scope", ["story", "free"])
def test_multicommand_red_retains_both_streams(tmp_path, scope):
    sentinel = tmp_path / "later"
    out, err = b"stdout\n" * 4000, b"stderr\n" * 4000
    selected = [
        command("print('first')"),
        command("import os; os.write(1,b'stdout\\n'*4000); os.write(2,b'stderr\\n'*4000); exit(7)"),
        command(f"from pathlib import Path; Path({str(sentinel)!r}).touch()"),
    ]
    if scope == "story":
        repo, env, g = make_repo(tmp_path, verify=" && ".join(selected))
        result = close(repo, env, "review")
    else:
        from close_free_card_cases import add_free_card, checkout_free, commit_on_free, spawn_free
        from close_helpers import free, free_repo

        repo, env, g = free_repo(tmp_path)
        assert free(repo, env, "evidence", "start").returncode == 0
        _branch, identity = checkout_free(g)
        commit_on_free(repo, g)
        add_free_card(env, identity, " && ".join(selected))
        repo = spawn_free(repo, env, g, tmp_path, identity, expected=2)
        import subprocess

        result = subprocess.run(
            [sys.executable, str(TEST_CLOSE), "free", "evidence", "review"],
            cwd=repo,
            env=env,
            capture_output=True,
            text=True,
        )
    assert result.returncode == 2
    assert "command 2 (exit 7)" in result.stderr and "stderr tail:" in result.stderr
    run = locator(result.stderr)
    manifest = json.loads((run / "run.json").read_text())
    import subprocess

    assert (
        manifest["head"]
        == subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
    )
    assert (
        manifest["tree"]
        == subprocess.check_output(["git", "write-tree"], cwd=repo, text=True).strip()
    )
    assert manifest["status"] == "failed"
    entry = manifest["commands"][1]
    assert entry["argv"] == shlex.split(selected[1])
    assert entry["index"] == 2 and entry["exit_result"] == 7
    assert entry["duration_seconds"] >= 0 and entry["ended_at"]
    assert (run / entry["stdout"]).read_bytes() == out
    assert (run / entry["stderr"]).read_bytes() == err
    assert len(manifest["commands"]) == 2 and not sentinel.exists()


def test_red_evidence_survives_rerun_and_repair(tmp_path):
    gate = tmp_path / "gate"
    gate.write_text("#!/bin/sh\nprintf original-out\nprintf original-err >&2\nexit 7\n")
    gate.chmod(0o755)
    repo, env, g = make_repo(tmp_path, verify=str(gate))
    red = close(repo, env, "review")
    original = locator(red.stderr)
    saved = {p.name: p.read_bytes() for p in original.iterdir()}
    gate.write_text("#!/bin/sh\nprintf green\n")
    repaired = close(repo, env, "repair")
    assert repaired.returncode == 2 and "green rerun" in repaired.stderr
    assert len(evidence(tmp_path)) == 2
    assert {p.name: p.read_bytes() for p in original.iterdir()} == saved
    assert close(repo, env, "review").returncode == 0
    assert len(evidence(tmp_path)) == 3
    (repo / "src" / "thing.py").write_text("A = 3\n")
    g("commit", "-qam", "later delta")
    assert close(repo, env, "review").returncode == 0
    assert len(evidence(tmp_path)) == 4
    assert {p.name: p.read_bytes() for p in original.iterdir()} == saved


def record_process(repo, env, argv, injection="", action=None, **options):
    import subprocess

    source = (
        f"import sys; sys.path.insert(0,{str(TEST_CLOSE.parent)!r}); import close\n"
        "import verify_receipt\n"
        + injection
        + f"\nred=verify_receipt.record('story-042','Verify reads: .','raw',{argv!r})\n"
        "print(red, file=sys.stderr); sys.exit(2 if red else 0)\n"
    )
    if action:
        source = source.split("\nred=verify_receipt.record")[0]
        source += f"\nsys.argv=['close.py','story','story-042',{action!r},'--merge-mode','local']\n"
        source += "sys.exit(close.main())\n"
    return subprocess.Popen(
        [sys.executable, "-c", source],
        cwd=repo,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        **options,
    )


def test_green_output_is_live(tmp_path):
    repo, env, _g = make_repo(tmp_path)
    ack = tmp_path / "ack"
    source = (
        "import os,time; from pathlib import Path; "
        "os.write(1,b'live-out'); os.write(2,b'live-err'); "
        f"ack=Path({str(ack)!r})\nwhile not ack.exists(): time.sleep(.01)\n"
    )
    process = record_process(repo, env, [[sys.executable, "-c", source]])
    try:
        received = observed(process)
        ack.touch()
        process.communicate(timeout=30)
        assert process.returncode == 0, received
        assert b"live-out" in received["stdout"] and b"live-err" in received["stderr"]
        run = json.loads(evidence(tmp_path)[0].read_text())
        assert run["status"] == "passed"
    finally:
        with suppress(ProcessLookupError):
            os.killpg(
                json.loads(evidence(tmp_path)[0].read_text())["commands"][0]["pid"], signal.SIGKILL
            )
        process.kill() if process.poll() is None else None
        process.communicate()


def test_launch_failure_has_no_exit_result(tmp_path):
    repo, env, _g = make_repo(tmp_path)
    for argv, status, result in (
        (["xp-no-such-executable"], "launch_error", None),
        ([sys.executable, "-c", "exit(127)"], "failed", 127),
    ):
        process = record_process(repo, env, [argv])
        _out, err = process.communicate(timeout=30)
        assert process.returncode == 2
        run = locator(err.decode())
        entry = json.loads((run / "run.json").read_text())["commands"][0]
        assert entry["status"] == status
        assert entry.get("exit_result") == result


def test_new_verify_invalidates_prior_green_receipt(tmp_path):
    repo, env, _g = make_repo(tmp_path)
    assert close(repo, env, "review").returncode == 0
    receipt = tmp_path / "data" / "markers" / "story-042.verify.json"
    assert receipt.exists()
    process = record_process(repo, env, [[sys.executable, "-c", "exit(7)"]])
    _out, err = process.communicate(timeout=30)
    assert process.returncode == 2 and locator(err.decode()).is_dir()
    assert not receipt.exists()
    assert close(repo, env, "review").returncode == 0
    sentinel = tmp_path / "should-not-run"
    injection = (
        "from pathlib import Path\noriginal=Path.unlink\n"
        "def unlink(self,*a,**k):\n"
        "    if self.name.endswith('.verify.json'): raise OSError('unlink fault')\n"
        "    return original(self,*a,**k)\nPath.unlink=unlink\n"
    )
    process = record_process(
        repo,
        env,
        [[sys.executable, "-c", f"from pathlib import Path; Path({str(sentinel)!r}).touch()"]],
        injection,
    )
    _out, err = process.communicate(timeout=30)
    assert process.returncode == 2 and b"unlink fault" in err and not sentinel.exists()


def spawn_capture(tmp_path, suffix=""):
    import subprocess

    from close_helpers import stub_reviewer

    source = "import os; os.write(2,b'err'*100000); exit(7)"
    repo, env, _g = make_repo(tmp_path, verify=command(source))
    stub_reviewer(tmp_path, result="reviewer" * 3000)
    script = (
        f"import sys; sys.path.insert(0,{str(TEST_CLOSE.parent)!r}); import spawn\n"
        "import story_stages, verify_log\n"
        "original_review=__import__('close').cmd_review\n"
        "def review(*a,**k):\n"
        "    rc=original_review(*a,**k)\n"
        f"    print({suffix!r},file=sys.stderr)\n"
        "    return rc\n__import__('close').cmd_review=review\n"
        "original=verify_log.forward\n"
        "def forward(stream,text):\n"
        "    result=original(stream,text)\n"
        "    if hasattr(stream, 'getvalue'): assert len(stream.getvalue())<=2000\n"
        "    return result\nverify_log.forward=forward\n"
        f"rc,state,refusal=story_stages.review_story(__import__('pathlib').Path({str(repo)!r}),'story-042')\n"
        "print('CAPTURED:'+__import__('json').dumps([rc,refusal]))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script], cwd=repo, env=env, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr[-3000:]
    captured = json.loads(result.stdout.split("CAPTURED:")[-1])
    assert captured[0] == 2 and len(captured[1]) <= 4001
    run = locator(captured[1])
    assert (run / "1.stderr").read_bytes() == b"err" * 100000


def test_spawn_capture_is_bounded(tmp_path):
    spawn_capture(tmp_path)


def test_spawn_refusal_keeps_verify_locator(tmp_path):
    spawn_capture(tmp_path, "suffix" * 1000)


@pytest.mark.parametrize(
    "boundary",
    [
        "directory",
        "root",
        "all-metadata",
        "started",
        "command-terminal",
        "short-write",
        "thread-start",
        "initial",
        "running",
        "terminal",
        "finalization",
        "open-stdout",
        "open-stderr",
        "write-stdout",
        "write-stderr",
        "flush",
        "close",
        "head",
        "tree",
        "receipt",
    ],
)
def test_evidence_failure_never_receipts(tmp_path, boundary):
    repo, env, _g = make_repo(tmp_path)
    sentinel = tmp_path / "later"
    from test_land_verify_receipt import evidence_fault

    reached = tmp_path / "injected-boundary"
    injection = evidence_fault(boundary, reached)
    argv = [
        [sys.executable, "-c", "import os; os.write(1,b'partial-out'); os.write(2,b'partial-err')"]
    ]
    if boundary not in ("receipt", "terminal", "finalization"):
        argv.append(
            [sys.executable, "-c", f"from pathlib import Path; Path({str(sentinel)!r}).touch()"]
        )
    plan = tmp_path / "data/plan.md"
    plan.write_text(
        plan.read_text().replace("Verify: true", "Verify: " + " && ".join(map(shlex.join, argv)))
    )
    from close_helpers import mint_ready

    mint_ready(repo, env)
    process = record_process(repo, env, argv, injection, action="review")
    _out, err = process.communicate(timeout=30)
    assert not sentinel.exists()
    marker = tmp_path / "data/markers/story-042.close.json"
    assert not marker.exists() or not json.loads(marker.read_text()).get("rounds")
    assert process.returncode == 2, err
    assert reached.exists(), err
    assert "refused" in (tmp_path / "data/reports/story-042.round-1.json").read_text()
    assert not (tmp_path / "data" / "markers" / "story-042.verify.json").exists()
    if boundary == "all-metadata":
        run = locator(err.decode())
        assert run.is_dir() and not (run / "run.json").exists()
    elif boundary not in ("directory", "root", "receipt"):
        run = locator(err.decode())
        manifest = json.loads((run / "run.json").read_text())
        assert manifest["status"] == ("running" if boundary == "finalization" else "evidence_error")
        if boundary == "finalization":
            assert "ended_at" not in manifest and manifest["commands"][-1]["exit_result"] == 0
    else:
        assert b"fault" in err


def observed(process):
    import selectors

    received = {"stdout": b"", "stderr": b""}
    with selectors.DefaultSelector() as selector:
        selector.register(process.stdout, selectors.EVENT_READ, "stdout")
        selector.register(process.stderr, selectors.EVENT_READ, "stderr")
        while not all(received.values()):
            events = selector.select(30)
            assert events, "hang guard: output absent"
            for key, _ in events:
                chunk = key.fileobj.read1(4096)
                assert chunk, received
                received[key.data] += chunk
    return received


@pytest.mark.parametrize("kill", [False, True], ids=["interrupt", "kill"])
def test_interrupt_preserves_partial_evidence(tmp_path, kill):
    repo, env, _g = make_repo(tmp_path)
    assert close(repo, env, "review").returncode == 0
    assert (tmp_path / "data/markers/story-042.verify.json").exists()
    source = "import os,time; os.write(1,b'short-out'); os.write(2,b'short-err'); time.sleep(300)"
    process = record_process(repo, env, [[sys.executable, "-c", source]], start_new_session=True)
    child_pid = None
    try:
        received = observed(process)
        run = next(
            p.parent for p in evidence(tmp_path) if json.loads(p.read_text())["status"] == "running"
        )
        saved = {p.name: p.read_bytes() for p in run.iterdir()}
        assert saved["1.stdout"] == b"short-out" and saved["1.stderr"] == b"short-err", received
        # The logger's child has its own group; save its PID for SIGKILL recovery cleanup.
        import subprocess

        child_pid = int(subprocess.check_output(["pgrep", "-P", str(process.pid)]).split()[0])
        process.send_signal(signal.SIGKILL if kill else signal.SIGINT)
        process.communicate(timeout=30)
        manifest = json.loads((run / "run.json").read_text())
        assert manifest["status"] == ("running" if kill else "interrupted")
        assert "exit_result" not in manifest["commands"][0]
        assert not (tmp_path / "data" / "markers" / "story-042.verify.json").exists()
        if kill:
            rerun = record_process(repo, env, [[sys.executable, "-c", "exit(0)"]])
            _out, err = rerun.communicate(timeout=30)
            assert rerun.returncode == 0 and str(run).encode() in err
            assert {p.name: p.read_bytes() for p in run.iterdir()} == saved
            assert len(evidence(tmp_path)) == 3
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
        if child_pid:
            with suppress(ProcessLookupError):
                os.killpg(child_pid, signal.SIGKILL)
        process.communicate()


def test_killed_parent_recovery_names_unfinished_run(tmp_path):
    test_interrupt_preserves_partial_evidence(tmp_path, True)


@pytest.mark.parametrize(
    "state", ["prepared", "missing", "malformed", "unreadable", "missing-output"]
)
def test_recovery_distinguishes_prior_states(tmp_path, state):
    repo, env, _g = make_repo(tmp_path)
    process = record_process(repo, env, [[sys.executable, "-c", "exit(0)"]])
    process.communicate(timeout=30)
    path = evidence(tmp_path)[0]
    record = json.loads(path.read_text())
    injection = ""
    if state == "prepared":
        record["status"] = "prepared"
        path.write_text(json.dumps(record))
    elif state == "missing":
        path.unlink()
    elif state == "malformed":
        path.write_text("{")
    elif state == "missing-output":
        (path.parent / "1.stderr").unlink()
    else:
        injection = (
            "from pathlib import Path\noriginal=Path.read_text\ndef read(self,*a,**k):\n"
            f"    if str(self)=={str(path)!r}: raise PermissionError('unreadable fault')\n"
            "    return original(self,*a,**k)\nPath.read_text=read\n"
        )
    saved = {p.name: p.read_bytes() for p in path.parent.iterdir()}
    process = record_process(repo, env, [[sys.executable, "-c", "exit(0)"]], injection)
    _out, err = process.communicate(timeout=30)
    assert str(path.parent).encode() in err
    diagnostic = (
        "unfinished Verify (prepared)" if state == "prepared" else state.split("-")[0] + " evidence"
    )
    assert diagnostic.encode() in err
    assert process.returncode == (0 if state == "prepared" else 2)
    assert {p.name: p.read_bytes() for p in path.parent.iterdir()} == saved
    assert len(list(path.parent.parent.iterdir())) == 2


def test_display_budget_does_not_bound_storage(tmp_path):
    repo, env, _g = make_repo(tmp_path)
    env["SECRET_SENTINEL"] = "must-not-dump-environment"
    argv = [
        sys.executable,
        "-c",
        "import os; os.write(1,b'out\\xff'*10000); os.write(2,b'err\\xfe'*10000); exit(7)",
        "long" * 3000,
    ]
    process = record_process(repo, env, [argv])
    _out, err = process.communicate(timeout=30)
    run = locator(err.decode())
    manifest = json.loads((run / "run.json").read_text())
    assert (run / "1.stdout").read_bytes() == b"out\xff" * 10000
    assert (run / "1.stderr").read_bytes() == b"err\xfe" * 10000
    assert manifest["commands"][0]["argv"] == argv
    assert env["SECRET_SENTINEL"] not in json.dumps(manifest)
    assert len(err.decode().split("refused:")[-1]) < 2500


@pytest.mark.parametrize("exit_result", [0, 7])
def test_exited_command_does_not_wait_for_descendant_pipes(tmp_path, exit_result):
    repo, env, _g = make_repo(tmp_path)
    ready = tmp_path / "descendant-ready"
    later = tmp_path / "later"
    descendant = (
        "import os,time; from pathlib import Path; "
        "os.write(1,b'descendant-out'); os.write(2,b'descendant-err'); "
        f"Path({str(ready)!r}).touch(); time.sleep(300)"
    )
    source = (
        "import subprocess,time; from pathlib import Path; "
        f"subprocess.Popen([{sys.executable!r},'-c',{descendant!r}]); "
        f"ready=Path({str(ready)!r})\n"
        "while not ready.exists(): time.sleep(.01)\n"
        f"raise SystemExit({exit_result})"
    )
    commands = [
        [sys.executable, "-c", source],
        [sys.executable, "-c", f"from pathlib import Path; Path({str(later)!r}).touch()"],
    ]
    process = record_process(repo, env, commands)
    try:
        _out, err = process.communicate(timeout=30)
        manifest_path = evidence(tmp_path)[0]
        manifest = json.loads(manifest_path.read_text())
        assert process.returncode == (2 if exit_result else 0), err
        assert manifest["status"] == ("failed" if exit_result else "passed")
        entry = manifest["commands"][0]
        assert entry["exit_result"] == exit_result
        assert (manifest_path.parent / entry["stdout"]).read_bytes() == b"descendant-out"
        assert (manifest_path.parent / entry["stderr"]).read_bytes() == b"descendant-err"
        assert later.exists() == (exit_result == 0)
        if exit_result:
            assert locator(err.decode()) == manifest_path.parent
    finally:
        for path in evidence(tmp_path):
            for entry in json.loads(path.read_text())["commands"]:
                if "pid" in entry:
                    with suppress(ProcessLookupError):
                        os.killpg(entry["pid"], signal.SIGKILL)
        if process.poll() is None:
            process.kill()
        process.communicate(timeout=30)


def test_spawn_locator_preserves_punctuation_in_data_path(tmp_path):
    root = tmp_path / "consumer — evidence"
    root.mkdir()
    spawn_capture(root, "suffix" * 1000)
