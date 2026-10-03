"""Lead recovery retains the reviewed tree and the producing stage's artifacts."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from close_helpers import SPAWN
from story_review_helpers import checkpoint, flow_repo, invoke


def worktree(repo, env, git, key):
    branch = "t/" + key + ("-demo-story" if key.startswith("story-") else "")
    assert git("branch", "-m", branch).returncode == 0
    assert git("checkout", "-q", "main").returncode == 0
    tree = Path(env["XP_DATA"]) / "worktrees" / key
    tree.parent.mkdir()
    assert git("worktree", "add", str(tree), branch).returncode == 0
    return tree


@pytest.mark.parametrize("scope", ["story", "free"])
@pytest.mark.parametrize("scenario", ["closer-blocked", "hook-refusal", "malformed-fixer"])
def test_ordinary_resume_never_replays_a_lead_handoff(tmp_path, scope, scenario):
    repo, env, git, key, events, _hooks = flow_repo(tmp_path, scope=scope, scenario=scenario)
    tree = worktree(repo, env, git, key)
    assert invoke(tree, env, key).returncode == 2
    before = events.read_bytes()
    state = checkpoint(env, key)
    original = Path(state["stages"]["solution"]["path"]).read_bytes()
    result = subprocess.run(
        [sys.executable, str(SPAWN), "resume", key],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2, result.stdout + result.stderr
    assert events.read_bytes() == before
    assert Path(state["stages"]["solution"]["path"]).read_bytes() == original
    assert checkpoint(env, key)["status"] != "completed"


@pytest.mark.parametrize("scope", ["story", "free"])
def test_explicit_lead_correction_can_start_new_sequence(tmp_path, scope):
    repo, env, git, key, events, _hooks = flow_repo(
        tmp_path, scope=scope, scenario="closer-blocked"
    )
    assert invoke(repo, env, key).returncode == 2
    old = checkpoint(env, key)
    preserved = {
        stage["path"]: Path(stage["path"]).read_bytes()
        for stage in old["stages"].values()
        if stage["status"] == "completed"
    }
    (repo / "src/thing.py").write_text("A = 4\n")
    assert git("commit", "-qam", "lead resolves concrete regression").returncode == 0
    binary = tmp_path / "bin/claude"
    binary.write_text(binary.read_text().replace("'closer-blocked'", "'clean'"))
    result = invoke(repo, env, key)
    assert result.returncode == 0, result.stderr
    assert events.read_text().splitlines() == ["solution", "fixer", "closer", "solution"]
    assert checkpoint(env, key)["id"] != old["id"]
    assert all(Path(path).read_bytes() == data for path, data in preserved.items())
    assert (repo / "src/thing.py").read_text() == "A = 4\n"


@pytest.mark.parametrize("scope", ["story", "free"])
@pytest.mark.parametrize("action", ["review", "acknowledge-validation"])
def test_close_and_resume_share_launch_exclusion(tmp_path, scope, action):
    from contextlib import chdir

    import close
    import resume

    repo, env, _git, key, events, _hooks = (
        flow_repo(tmp_path, scope=scope) if action == "review" else pending_disposition(tmp_path)
    )
    # Acquire the same OS lock a live spawn holds, then execute its internal close.
    previous = dict(os.environ)
    os.environ.update(env)
    try:
        with chdir(repo):
            held, error = resume.acquire(Path(env["XP_DATA"]), key)
            assert not error
            try:
                assert close.cmd_review(key, held=held, explicit=False) == (
                    0 if action == "review" else 2
                )
                before = checkpoint(env, key)
                count = events.read_bytes()
                args = ("--reason", "service recovered") if action != "review" else ()
                result = invoke(repo, env, key, action, *args)
                assert result.returncode == 2 and "launch in progress" in result.stderr
                assert checkpoint(env, key) == before
                assert events.read_bytes() == count
            finally:
                held.close()
    finally:
        os.environ.clear()
        os.environ.update(previous)


def pending_disposition(tmp_path):
    gate = tmp_path / "gate"
    gate.write_text("#!/bin/sh\necho RED >&2\nexit 8\n")
    gate.chmod(0o755)
    repo, env, git, key, events, hooks = flow_repo(tmp_path, verify=str(gate))
    assert invoke(repo, env, key).returncode == 2
    gate.write_text("#!/bin/sh\necho GREEN\n")
    assert invoke(repo, env, key).returncode == 2
    assert checkpoint(env, key)["status"] == "awaiting-disposition"
    return repo, env, git, key, events, hooks


@pytest.mark.parametrize(
    "fault", ["role", "empty", "source", "card", "report", "evidence", "marker"]
)
def test_disposition_cannot_certify_changed_or_missing_authority(tmp_path, fault):
    repo, env, git, key, events, _hooks = pending_disposition(tmp_path)
    state = checkpoint(env, key)
    reason = "external service recovered"
    if fault == "role":
        env["XP_ROLE"] = "fixer"
    elif fault == "empty":
        reason = "   "
    elif fault == "source":
        (repo / "src/thing.py").write_text("A = 7\n")
        git("commit", "-qam", "new source")
    elif fault == "card":
        path = Path(env["XP_DATA"]) / "plan.md"
        path.write_text(path.read_text().replace("Verify:", "Verify: true &&"))
    elif fault == "report":
        Path(state["stages"]["solution"]["path"]).write_text('{"actionable":[],"blocking":["B"]}')
    elif fault == "marker":
        path = Path(env["XP_DATA"]) / "markers" / f"{key}.close.json"
        path.write_text(path.read_text() + " ")
    else:
        (Path(state["validation"][0]["path"]) / "run.json").unlink()
    before = events.read_bytes()
    result = invoke(repo, env, key, "acknowledge-validation", "--reason", reason)
    assert result.returncode == 2, result.stdout + result.stderr
    assert events.read_bytes() == before
    assert checkpoint(env, key)["status"] == "awaiting-disposition"


@pytest.mark.parametrize(
    "output", ["{}", '{"blocking":[],"blocking":["B"]}', "[1]", "\u007b", "absent"]
)
def test_bad_output_preserves_original_bytes_and_producer(tmp_path, output):
    repo, env, _git, key, _events, _hooks = flow_repo(tmp_path)
    binary = tmp_path / "bin/claude"
    text = binary.read_text().replace(
        "Path(path).write_text(json.dumps(report))",
        "pass" if output == "absent" else f"Path(path).write_text({output!r})",
    )
    binary.write_text(text)
    result = invoke(repo, env, key)
    assert result.returncode == 2 and "solution" in result.stderr
    state = checkpoint(env, key)
    assert state["status"] == "incomplete"
    path = Path(state["stages"]["solution"]["path"])
    assert not path.exists() if output == "absent" else path.read_text() == output


def test_terminal_red_survives_interruption_before_checkpoint_publication(tmp_path, monkeypatch):
    from contextlib import chdir

    import close
    import review_validation
    import verify_receipt

    gate = tmp_path / "gate"
    gate.write_text("#!/bin/sh\necho ORIGINAL-RED >&2\nexit 9\n")
    gate.chmod(0o755)
    repo, env, _git, key, events, _hooks = flow_repo(tmp_path, verify=str(gate))
    original = verify_receipt.record

    def interrupted(*args):
        assert original(*args)
        raise KeyboardInterrupt

    for name, value in env.items():
        monkeypatch.setenv(name, value)
    with chdir(repo), monkeypatch.context() as patch:
        patch.setattr(review_validation.verify_receipt, "record", interrupted)
        with pytest.raises(KeyboardInterrupt):
            close.cmd_review(key)
    state = checkpoint(env, key)
    assert state["status"] == "validation" and not state["validation"]
    gate.write_text("#!/bin/sh\necho GREEN\n")
    result = invoke(repo, env, key)
    assert result.returncode == 2, result.stderr
    assert checkpoint(env, key)["status"] == "awaiting-disposition"
    assert events.read_text().splitlines() == ["solution"]


@pytest.mark.parametrize("fault", ["no-green", "findings"])
def test_disposition_cannot_clear_unresolved_checks_or_findings(tmp_path, fault):
    repo, env, _git, key, _events, _hooks = pending_disposition(tmp_path)
    state = checkpoint(env, key)
    from contextlib import chdir

    import close
    import review
    import review_sequence

    previous = dict(os.environ)
    os.environ.update(env)
    try:
        with chdir(repo):
            if fault == "no-green":
                state["validation"].pop()
                review_sequence.save(key, state)
            else:
                marker = close.marker_path(key)
                data = json.loads(marker.read_text())
                data["rounds"][-1]["blocking"] = ["unresolved authorized AC"]
                marker.write_text(json.dumps(data))
                state["marker_identity"] = review.marker_digest(marker)
                review_sequence.save(key, state)
    finally:
        os.environ.clear()
        os.environ.update(previous)
    result = invoke(repo, env, key, "acknowledge-validation", "--reason", "service recovered")
    assert result.returncode == 2, result.stderr
    assert checkpoint(env, key)["status"] == "awaiting-disposition"


@pytest.mark.meta
@pytest.mark.parametrize("guard", ["lock", "tree", "terminal", "publication", "land", "logs"])
def test_recovery_guard_detects_its_fault(tmp_path, monkeypatch, guard):
    import shutil

    from close_helpers import PLUGIN

    def guarantee(root):
        root.mkdir()
        if guard == "logs":
            test_stage_logs_survive_later_stages_and_explicit_review(root, "free")
        elif guard == "lock":
            test_close_and_resume_share_launch_exclusion(root, "story", "review")
        elif guard == "tree":
            test_disposition_cannot_certify_changed_or_missing_authority(root, "source")
        elif guard == "land":
            repo, env, git, key, _events, _hooks = pending_disposition(root)
            before = git("rev-parse", "main").stdout
            result = invoke(repo, env, key, "land", "--merge-mode", "local")
            assert result.returncode == 2
            assert git("rev-parse", "main").stdout == before
        elif guard == "publication":
            test_terminal_red_survives_interruption_before_checkpoint_publication(root, monkeypatch)
        else:
            repo, env, _git, key, events, _hooks = flow_repo(root, scenario="closer-blocked")
            assert invoke(repo, env, key).returncode == 2
            count = events.read_bytes()
            result = invoke(repo, env, key)
            assert result.returncode == 2 and events.read_bytes() == count

    guarantee(tmp_path / "control")
    installed = tmp_path / "installed"
    shutil.copytree(PLUGIN, installed)
    if guard == "logs":
        path = installed / "scripts/close/review_sequence.py"
        text = (
            path.read_text()
            .replace("log_id=path.stem,", 'log_id="",')
            .replace('        "log": str(data_root() / "logs" / (path.stem + ".log")),\n', "")
        )
    elif guard == "lock":
        path = installed / "scripts/spawn/resume.py"
        text = path.read_text().replace(
            "fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)", "pass"
        )
    elif guard == "tree":
        path = installed / "scripts/close/review_validation.py"
        text = path.read_text().replace(
            'if card != sequence["card"] or measure(story_id, card) != sequence["output"]:',
            "if False:",
        )
    elif guard == "land":
        path = installed / "scripts/close/land.py"
        text = path.read_text().replace('if sequence["status"] != "completed":', "if False:")
    elif guard == "publication":
        path = installed / "scripts/close/review_validation.py"
        text = path.read_text().replace("for path in sorted(before):", "for path in []:")
    else:
        path = installed / "scripts/close/review_sequence.py"
        text = path.read_text().replace('if sequence["status"] == "blocked":', "if False:")
    path.write_text(text)
    monkeypatch.setenv("XP_FLOW_TEST_CLOSE", str(installed / "scripts/close.py"))
    with pytest.raises(AssertionError):
        guarantee(tmp_path / "mutant")


@pytest.mark.parametrize("scope", ["story", "free"])
def test_stage_logs_survive_later_stages_and_explicit_review(tmp_path, scope):
    repo, env, git, key, _events, _hooks = flow_repo(tmp_path, scope=scope, scenario="fixed")
    binary = tmp_path / "bin/claude"
    binary.write_text(
        binary.read_text().replace("'result':'complete'", "'result':stage+str(os.getpid())")
    )
    assert invoke(repo, env, key).returncode == 0
    first = checkpoint(env, key)
    paths = [
        Path(
            item.get(
                "log",
                str(
                    Path(env["XP_DATA"])
                    / "logs"
                    / (
                        f"{key}-{'reviewer' if name == 'solution' else name}.log"
                        if scope == "story"
                        else "story-reviewer-review.log"
                    )
                ),
            )
        )
        for name, item in first["stages"].items()
    ]
    assert len(set(paths)) == 3
    original = {path: path.read_bytes() for path in paths}
    (repo / "src/thing.py").write_text("A = 4\n")
    assert git("commit", "-qam", "lead work").returncode == 0
    binary = tmp_path / "bin/claude"
    binary.write_text(binary.read_text().replace("'fixed'", "'clean'"))
    assert invoke(repo, env, key).returncode == 0
    assert all(path.read_bytes() == raw for path, raw in original.items())


@pytest.mark.parametrize("harness", ["claude", "codex"])
@pytest.mark.parametrize("drop", ["out of scope", {"finding": "out of scope", "reason": ""}])
def test_correction_receives_measured_refusal_and_preserves_attempt(tmp_path, harness, drop):
    repo, env, git, key, events, hooks = flow_repo(tmp_path, harness)
    expected = tmp_path / "expected-refusal"
    binary = tmp_path / "bin" / harness
    binary.write_text(
        binary.read_text().replace(
            "path=re.search",
            f"report['dropped']=[{drop!r}]\n"
            f"expected=Path({str(expected)!r})\n"
            "if expected.exists() and expected.read_text() in prompt:\n"
            "    report['dropped']=[{'finding':'out of scope',"
            "'reason':'card excludes this input'}]\n"
            "path=re.search",
        )
    )
    head = git("rev-parse", "HEAD").stdout
    source = (repo / "src/thing.py").read_bytes()
    first = invoke(repo, env, key)
    assert first.returncode == 2
    before = checkpoint(env, key)
    assert before["status"] == "incomplete"
    original = Path(before["stages"]["solution"]["path"])
    raw = original.read_bytes()
    assert json.loads(raw)["dropped"] == [drop]
    expected.write_text(before["problem"])

    corrected = invoke(repo, env, key)
    assert corrected.returncode == 0, corrected.stderr
    after = checkpoint(env, key)
    assert after["id"] == before["id"]
    assert after["start"] == before["start"]
    assert after["output"] == before["output"]
    assert after["stages"]["solution"]["prior_attempts"] == [before["stages"]["solution"]]
    assert Path(after["stages"]["solution"]["path"]) != original
    assert original.read_bytes() == raw
    assert git("rev-parse", "HEAD").stdout == head
    assert (repo / "src/thing.py").read_bytes() == source
    assert not git("status", "--porcelain").stdout
    assert not hooks.exists()
    assert events.read_text().splitlines() == ["solution", "solution"]
    assert after["status"] == "completed"


@pytest.mark.meta
def test_correction_diagnostic_guard_detects_omission(tmp_path, monkeypatch):
    import shutil

    from close_helpers import PLUGIN

    control = tmp_path / "control"
    control.mkdir()
    test_correction_receives_measured_refusal_and_preserves_attempt(control, "claude", "drop")
    installed = tmp_path / "installed"
    shutil.copytree(PLUGIN, installed)
    path = installed / "scripts/close/review_sequence.py"
    path.write_text(path.read_text().replace('+ sequence["problem"]', '+ ""'))
    monkeypatch.setenv("XP_FLOW_TEST_CLOSE", str(installed / "scripts/close.py"))
    mutant = tmp_path / "mutant"
    mutant.mkdir()
    with pytest.raises(AssertionError):
        test_correction_receives_measured_refusal_and_preserves_attempt(mutant, "claude", "drop")


@pytest.mark.parametrize("harness", ["claude", "codex"])
@pytest.mark.parametrize("producer", ["fixer", "closer"])
def test_fixed_object_correction_preserves_committed_work(tmp_path, harness, producer):
    repo, env, git, key, events, hooks = flow_repo(tmp_path, harness, scenario="fixed")
    expected = tmp_path / "expected-refusal"
    binary = tmp_path / "bin" / harness
    binary.write_text(
        binary.read_text()
        .replace(
            "if stage=='fixer':",
            "if stage=='fixer' and 'Correct only the incomplete report' not in prompt:",
        )
        .replace(
            "path=re.search",
            f"if stage=={producer!r}:\n"
            "    report['fixed']=[{'finding':'A must equal 3'}]\n"
            f"    expected=Path({str(expected)!r})\n"
            "    if expected.exists() and expected.read_text() in prompt "
            "and re.search(r'\\bstrings?\\b',expected.read_text()):\n"
            "        report['fixed']=['A must equal 3']\n"
            "path=re.search",
        )
    )
    assert invoke(repo, env, key).returncode == 2
    before = checkpoint(env, key)
    assert before["status"] == "incomplete" and before["producer"] == producer
    original = Path(before["stages"][producer]["path"])
    raw = original.read_bytes()
    assert json.loads(raw)["fixed"] == [{"finding": "A must equal 3"}]
    head = git("rev-parse", "HEAD").stdout
    expected.write_text(before["problem"])
    result = invoke(repo, env, key)
    assert result.returncode == 0, result.stderr
    after = checkpoint(env, key)
    assert after["id"] == before["id"] and after["output"] == before["output"]
    assert after["stages"][producer]["prior_attempts"] == [before["stages"][producer]]
    assert after["stages"][producer]["report"]["fixed"] == ["A must equal 3"]
    assert original.read_bytes() == raw
    assert git("rev-parse", "HEAD").stdout == head
    assert (repo / "src/thing.py").read_text() == "A = 3\n"
    assert hooks.read_text().splitlines() == ["hook"]
    assert events.read_text().splitlines() == (
        ["solution", "fixer", "fixer", "closer"]
        if producer == "fixer"
        else ["solution", "fixer", "closer", "closer"]
    )
    assert after["status"] == "completed"
