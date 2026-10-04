import json
import signal
import subprocess
import sys

import pytest
from close_helpers import FIX_PATCH, SPAWN, close, make_repo, mint_ready, stub_reviewer


def counted_repo(tmp_path, declaration=None):
    calls = tmp_path / "verify-calls"
    repo, env, git = make_repo(tmp_path, verify=f"sh -c 'echo call >> {calls}'")
    if declaration is not None:
        plan = tmp_path / "data" / "plan.md"
        plan.write_text(
            plan.read_text().replace("Verify: ", f"Verify reads: {declaration}\nVerify: ")
        )
        mint_ready(repo, env)
    reviewed = close(repo, env, "review")
    assert reviewed.returncode == 0, reviewed.stderr
    assert calls.read_text().splitlines() == ["call"]
    return repo, env, git, calls


def trunk_change(repo, git, path):
    branch = git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    assert git("checkout", "main").returncode == 0
    target = repo / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("trunk change\n")
    assert git("add", path).returncode == 0
    assert git("commit", "-qm", "trunk moved").returncode == 0
    assert git("checkout", branch).returncode == 0


def test_exact_review_tree_reuses_verify(tmp_path):
    verify_calls = tmp_path / "verify-calls"
    tier_calls = tmp_path / "tier-calls"
    repo, env, git = make_repo(
        tmp_path,
        verify=f"sh -c 'echo call >> {verify_calls}'",
        files="src/thing.py, .xp/config.yml",
    )
    config = repo / ".xp" / "config.yml"
    config.write_text(
        config.read_text().replace("story: true", f"story: sh -c 'echo call >> {tier_calls}'")
    )
    git("add", ".xp/config.yml")
    git("commit", "-qm", "configure tier")
    assert close(repo, env, "review").returncode == 0
    assert verify_calls.read_text().splitlines() == ["call"]
    landed = close(repo, env, "land")
    assert landed.returncode == 0, landed.stderr
    assert verify_calls.read_text().splitlines() == ["call"]
    assert tier_calls.read_text().splitlines() == ["call"]
    assert "skipped on exact tree" in landed.stdout
    assert not (tmp_path / "data/markers/story-042.verify.json").exists()


@pytest.mark.parametrize(
    ("declaration", "path", "said"),
    [
        (None, "docs/x.md", "ran: gated tree changed; no Verify reads declaration"),
        ("src/app/", "docs/x.md", "skipped on declared inputs"),
        (
            "src/app/",
            "src/app/y.py",
            "ran: trunk merge changed declared Verify reads: src/app/y.py",
        ),
        (":(bogus)src/app/", "docs/x.md", "ran: git could not match Verify reads"),
    ],
)
def test_merge_inputs_control_reuse(tmp_path, declaration, path, said):
    repo, env, git, calls = counted_repo(tmp_path, declaration)
    trunk_change(repo, git, path)
    landed = close(repo, env, "land")
    assert landed.returncode == 0, landed.stderr
    skips = said.startswith("skipped")
    assert len(calls.read_text().splitlines()) == (1 if skips else 2)
    assert f"Verify {said}" in landed.stdout
    if skips:
        assert declaration in landed.stdout and path in landed.stdout


@pytest.mark.parametrize("declaration", [None, "src/app/"])
def test_story_commit_after_review_runs_verify(tmp_path, declaration):
    repo, env, git, calls = counted_repo(tmp_path, declaration)
    (repo / "src" / "thing.py").write_text("A = 3\n")
    git("add", "src/thing.py")
    git("commit", "-qm", "later story work")
    landed = close(repo, env, "land")
    assert landed.returncode == 0, landed.stderr
    assert len(calls.read_text().splitlines()) == 2
    assert "Verify ran:" in landed.stdout


@pytest.mark.parametrize("condition", ["missing", "unreadable"])
def test_receipt_failure_runs_verify_and_names_state(tmp_path, condition):
    repo, env, _git, calls = counted_repo(tmp_path)
    receipt = tmp_path / "data" / "markers" / "story-042.verify.json"
    if condition == "missing":
        receipt.unlink()
    else:
        receipt.write_text("{bad json")
    landed = close(repo, env, "land")
    assert landed.returncode == 0, landed.stderr
    assert len(calls.read_text().splitlines()) == 2
    assert f"Verify ran: Verify receipt {condition}" in landed.stdout


def test_receipt_records_reviewed_tree_and_commands(tmp_path):
    _repo, _env, git, _calls = counted_repo(tmp_path)
    receipt = json.loads((tmp_path / "data/markers/story-042.verify.json").read_text())
    assert receipt["tree"] == git("write-tree").stdout.strip()
    assert receipt["head"] == git("rev-parse", "HEAD").stdout.strip()
    assert receipt["raw"] and receipt["verify"]
    assert receipt["reads"] is None


def test_reviewer_patch_tree_is_the_receipted_tree(tmp_path):
    repo, env, git = make_repo(tmp_path)
    stub_reviewer(tmp_path, patch=FIX_PATCH)
    reviewed = close(repo, env, "review")
    assert reviewed.returncode == 0, reviewed.stderr
    receipt = json.loads((tmp_path / "data/markers/story-042.verify.json").read_text())
    assert receipt["tree"] == git("write-tree").stdout.strip()
    assert receipt["head"] == git("rev-parse", "HEAD").stdout.strip()
    landed = close(repo, env, "land")
    assert landed.returncode == 0, landed.stderr
    assert "skipped on exact tree" in landed.stdout


def test_interrupted_review_verify_leaves_no_receipt(tmp_path):
    stopper = tmp_path / "stopper"
    stopper.write_text("#!/bin/sh\nkill -TERM $PPID\n")
    stopper.chmod(0o755)
    repo, env, _git = make_repo(tmp_path, verify=str(stopper))
    result = close(repo, env, "review")
    assert result.returncode == -signal.SIGTERM, result.stderr
    assert not (tmp_path / "data/markers/story-042.verify.json").exists()


@pytest.mark.parametrize("leg", ["ready", "amend"])
@pytest.mark.parametrize("line", ["Verify reads: /abs/app", "Verify reads: src/, ,docs/"])
def test_malformed_verify_reads_is_refused_before_review(tmp_path, leg, line):
    repo, env, _git = make_repo(tmp_path)
    plan = tmp_path / "data" / "plan.md"
    plan.write_text(plan.read_text().replace("Verify: ", f"{line}\nVerify: "))
    if leg == "ready":
        with pytest.raises(AssertionError, match="Verify reads:"):
            mint_ready(repo, env)
        return
    refused = subprocess.run(
        [sys.executable, str(SPAWN), "amend", "story-042", "--reason", "declare inputs"],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
    )
    assert refused.returncode != 0 and "Verify reads:" in refused.stderr, refused.stderr


def test_verify_reads_is_not_files_scope():
    from review_scope import declared_files

    assert declared_files("Files: src/thing.py\nVerify reads: src/app/\nVerify: true") == {
        "src/thing.py"
    }


@pytest.mark.parametrize("field", ["Verify", "Verify reads"])
def test_amended_card_field_runs_verify(tmp_path, field):
    repo, env, _git, calls = counted_repo(tmp_path, "src/app/")
    plan = tmp_path / "data/plan.md"
    if field == "Verify reads":
        plan.write_text(plan.read_text().replace("Verify reads: src/app/", "Verify reads: docs/"))
    else:
        plan.write_text(plan.read_text().replace("Verify: sh -c", "Verify: env sh -c"))
    mint_ready(repo, env)
    landed = close(repo, env, "land")
    assert landed.returncode == 0, landed.stderr
    assert len(calls.read_text().splitlines()) == 2
    assert f"Verify ran: {field}" in landed.stdout


def test_red_review_leaves_no_receipt(tmp_path):
    repo, env, _git, calls = counted_repo(tmp_path)
    receipt = tmp_path / "data/markers/story-042.verify.json"
    assert receipt.exists()
    plan = tmp_path / "data/plan.md"
    plan.write_text(plan.read_text().replace("Verify: sh -c", "Verify: false && sh -c"))
    mint_ready(repo, env)
    red = close(repo, env, "review")
    assert red.returncode != 0
    assert not receipt.exists()
    assert calls.read_text().splitlines() == ["call"]


def test_slate_bundle_uses_shipped_card_template(tmp_path):
    from slate_review_helpers import slate_repo, slate_review, stub_slate_reviewer

    repo, env = slate_repo(tmp_path)
    launch = stub_slate_reviewer(tmp_path)
    assert "Verify reads:" not in (tmp_path / "data/plan.md").read_text()
    result = slate_review(repo, env)
    assert result.returncode == 0, result.stderr
    prompt = json.loads(launch.read_text())["prompt"]
    assert "## Shipped card template" in prompt
    assert "Verify reads:" in prompt


def test_no_commands_and_child_signal_cannot_mint_verify_receipt(tmp_path):
    from test_verify_evidence import locator, record_process

    repo, env, _g = make_repo(tmp_path)
    for commands, expected in (
        ([], "empty"),
        (
            [[sys.executable, "-c", "import os,signal; os.kill(os.getpid(),signal.SIGTERM)"]],
            "interrupted",
        ),
    ):
        process = record_process(repo, env, commands)
        _out, err = process.communicate(timeout=30)
        assert process.returncode == 2, err
        run = json.loads((locator(err.decode()) / "run.json").read_text())
        assert run["status"] == expected
        assert not (tmp_path / "data" / "markers" / "story-042.verify.json").exists()


@pytest.mark.parametrize("position", [1, 2])
def test_command_success_is_not_a_finalized_run(tmp_path, position):
    import os
    from contextlib import suppress

    from test_verify_evidence import evidence, observed, record_process

    repo, env, _g = make_repo(tmp_path)
    sentinel = tmp_path / "later"
    injection = f"""
import verify_log, time
original=verify_log.save
def save(directory,manifest):
    original(directory,manifest)
    entries=manifest['commands']
    if len(entries)=={position} and entries[-1]['status']=='passed' and 'ended_at' not in manifest:
        print('pause-out',flush=True)
        print('pause-err',file=sys.stderr,flush=True)
        time.sleep(300)
verify_log.save=save
"""
    commands = [[sys.executable, "-c", "exit(0)"], [sys.executable, "-c", "exit(0)"]]
    if position == 1:
        commands[1] = [
            sys.executable,
            "-c",
            f"from pathlib import Path; Path({str(sentinel)!r}).touch()",
        ]
    process = record_process(repo, env, commands, injection, start_new_session=True)
    try:
        observed(process)
        run = evidence(tmp_path)[0].parent
        saved = {p.name: p.read_bytes() for p in run.iterdir()}
        manifest = json.loads(saved["run.json"])
        assert manifest["commands"][-1]["exit_result"] == 0
        assert manifest["status"] == "running" and "ended_at" not in manifest
        process.kill()
        process.communicate(timeout=30)
        rerun = record_process(repo, env, [[sys.executable, "-c", "exit(0)"]])
        _out, err = rerun.communicate(timeout=30)
        assert rerun.returncode == 0 and b"unfinished Verify (running)" in err
        assert str(run).encode() in err and not sentinel.exists()
        assert {p.name: p.read_bytes() for p in run.iterdir()} == saved
    finally:
        with suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
        process.communicate()


def evidence_fault(boundary, reached):
    return f"""
import verify_log
from pathlib import Path
boundary={boundary!r}
reached=Path({str(reached)!r})
def fault(message,kind=OSError):
    reached.touch()
    raise kind(message)
original_save=verify_log.save
def save(directory,manifest):
    state=manifest['status']
    entries=manifest['commands']
    if boundary=='all-metadata': fault('metadata fault')
    if boundary=='finalization' and 'ended_at' in manifest: fault('finalization fault')
    if boundary=='started' and entries and entries[-1]['status']=='running':
        fault('started fault')
    if (boundary=='command-terminal' and entries and entries[-1]['status']=='passed'
            and 'ended_at' not in manifest):
        fault('command-terminal fault')
    if boundary== 'initial' and state=='prepared': fault('initial fault')
    if boundary== 'running' and state=='running': fault('running fault')
    if boundary=='terminal' and state=='passed' and 'ended_at' in manifest:
        fault('terminal fault')
    return original_save(directory,manifest)
verify_log.save=save
if boundary=='root':
    original_mkdir=Path.mkdir
    def mkdir(self,*a,**k):
        if self.name=='verify': fault('root fault')
        return original_mkdir(self,*a,**k)
    Path.mkdir=mkdir
if boundary=='thread-start':
    original_start=verify_log.threading.Thread.start
    def start(self,*a,**k):
        if self._target is verify_log.drain: fault('thread fault',RuntimeError)
        return original_start(self,*a,**k)
    verify_log.threading.Thread.start=start
if boundary=='directory':
    original_mkdtemp=verify_log.tempfile.mkdtemp
    def mkdir(*a,**k):
        prefix=k.get('prefix',a[1] if len(a)>1 else '')
        if prefix.startswith(('xp-source-', 'xp-execution-')):
            return original_mkdtemp(*a,**k)
        fault('directory fault')
    verify_log.tempfile.mkdtemp=mkdir
original_open=Path.open
class Output:
    def __init__(self,output): self.output=output
    def __enter__(self): return self
    def __exit__(self,*a):
        self.output.close()
        if boundary=='close': fault('close fault')
    def write(self,chunk):
        if boundary=='short-write':
            reached.touch()
            return self.output.write(chunk[:1])
        result=self.output.write(chunk)
        if boundary=='write-'+self.output.name.rsplit('.',1)[-1]:
            fault('write fault')
        return result
    def flush(self):
        if boundary=='flush': fault('flush fault')
        self.output.flush()
def open_file(self,mode='r',*a,**k):
    stream=self.suffix.removeprefix('.')
    if mode=='wb' and stream in ('stdout','stderr'):
        if boundary=='open-'+stream: fault('open fault')
        return Output(original_open(self,mode,*a,**k))
    return original_open(self,mode,*a,**k)
Path.open=open_file
original_git=verify_log.git
def git(*args,**kwargs):
    if boundary in ('head','tree') and args[0]==('rev-parse' if boundary=='head' else 'write-tree'):
        import subprocess
        reached.touch()
        return subprocess.CompletedProcess(args,1,'','measurement fault')
    return original_git(*args,**kwargs)
verify_log.git=git
original_write=Path.write_text
def write_text(self,*a,**k):
    if boundary=='receipt' and self.name.endswith('.verify.json'): fault('receipt fault')
    return original_write(self,*a,**k)
Path.write_text=write_text
"""


def test_stream_failure_stops_blocked_child(tmp_path):
    import os
    from contextlib import suppress

    from test_verify_evidence import locator, record_process

    repo, env, _g = make_repo(tmp_path)
    pid_file = tmp_path / "child-pid"
    reached = tmp_path / "injected-boundary"
    source = (
        "import os,time; from pathlib import Path; "
        f"Path({str(pid_file)!r}).write_text(str(os.getpid())); "
        "os.write(1,b'blocked-out'); os.write(2,b'blocked-err'); time.sleep(300)"
    )
    process = record_process(
        repo, env, [[sys.executable, "-c", source]], evidence_fault("write-stdout", reached)
    )
    try:
        _out, err = process.communicate(timeout=30)
        assert process.returncode == 2 and reached.exists(), err
        run = json.loads((locator(err.decode()) / "run.json").read_text())
        assert run["status"] == "evidence_error"
        assert run["commands"][0]["pid"] == int(pid_file.read_text())
        with pytest.raises(ProcessLookupError):
            os.kill(int(pid_file.read_text()), 0)
        assert not (tmp_path / "data/markers/story-042.verify.json").exists()
    finally:
        if process.poll() is None:
            process.kill()
        if pid_file.exists():
            with suppress(ProcessLookupError):
                os.killpg(int(pid_file.read_text()), signal.SIGKILL)
        process.communicate()
