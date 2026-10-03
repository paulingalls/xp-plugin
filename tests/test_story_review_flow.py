"""One solution review, one conditional fix and close, then lead-owned problems."""

import pytest
from story_review_helpers import checkpoint, flow_repo, invoke


@pytest.mark.parametrize("harness", ["claude", "codex"])
@pytest.mark.parametrize("scope", ["story", "free"])
def test_clean_review_skips_fix_and_close(tmp_path, harness, scope):
    repo, env, git, key, events, hooks = flow_repo(tmp_path, harness, scope)
    head = git("rev-parse", "HEAD").stdout
    result = invoke(repo, env, key)
    assert result.returncode == 0, result.stderr
    assert events.read_text().splitlines() == ["solution"]
    assert git("rev-parse", "HEAD").stdout == head
    assert not hooks.exists()
    assert checkpoint(env, key)["status"] == "completed"


@pytest.mark.parametrize("harness", ["claude", "codex"])
@pytest.mark.parametrize("scope", ["story", "free"])
def test_authorized_fix_commits_once_and_gets_narrow_close(tmp_path, harness, scope):
    repo, env, git, key, events, hooks = flow_repo(tmp_path, harness, scope, "fixed")
    before = git("rev-parse", "HEAD").stdout.strip()
    result = invoke(repo, env, key)
    assert result.returncode == 0, result.stderr
    assert events.read_text().splitlines() == ["solution", "fixer", "closer"]
    assert hooks.read_text().splitlines() == ["hook"]
    assert git("rev-list", "--count", before + "..HEAD").stdout.strip() == "1"
    assert git("show", "-s", "--format=%an", "HEAD").stdout.strip() != "xp story-reviewer"
    assert checkpoint(env, key)["status"] == "completed"


@pytest.mark.parametrize("scenario", ["closer-blocked", "hook-refusal"])
def test_remaining_problem_hands_back_without_relaunch(tmp_path, scenario):
    repo, env, git, key, events, _hooks = flow_repo(tmp_path, scenario=scenario)
    result = invoke(repo, env, key)
    assert result.returncode == 2
    sequence = checkpoint(env, key)
    assert sequence["status"] == "blocked"
    count = events.read_text()
    retry = invoke(repo, env, key)
    assert retry.returncode == 2
    assert events.read_text() == count
    if scenario == "hook-refusal":
        assert (repo / "src/thing.py").read_text() == "A = 3\n"
        assert git("diff", "--cached").stdout
    else:
        assert sequence["stages"]["solution"]["status"] == "completed"
        assert sequence["stages"]["fixer"]["status"] == "completed"


def test_same_tree_green_retry_requires_lead_disposition(tmp_path):
    gate = tmp_path / "gate"
    gate.write_text("#!/bin/sh\necho red >&2\nexit 7\n")
    gate.chmod(0o755)
    repo, env, _git, key, events, _hooks = flow_repo(tmp_path, verify=str(gate))
    result = invoke(repo, env, key)
    assert result.returncode == 2
    first = checkpoint(env, key)
    assert first["stages"]["solution"]["status"] == "completed"
    from pathlib import Path

    path = Path(first["validation"][0]["path"])
    saved = {p.name: p.read_bytes() for p in path.iterdir()}
    gate.write_text("#!/bin/sh\necho green\n")
    retry = invoke(repo, env, key)
    assert retry.returncode == 2
    assert events.read_text().splitlines() == ["solution"]
    assert checkpoint(env, key)["status"] == "awaiting-disposition"
    ack = invoke(
        repo, env, key, "acknowledge-validation", "--reason", "external test service recovered"
    )
    assert ack.returncode == 0, ack.stderr
    assert checkpoint(env, key)["status"] == "completed"
    assert {p.name: p.read_bytes() for p in path.iterdir()} == saved


@pytest.mark.parametrize("producer", ["solution", "fixer", "closer"])
def test_malformed_stage_preserves_work_and_names_producer(tmp_path, producer):
    repo, env, _git, key, events, _hooks = flow_repo(tmp_path, scenario="malformed-" + producer)
    result = invoke(repo, env, key)
    assert result.returncode == 2 and producer in result.stderr
    sequence = checkpoint(env, key)
    assert sequence["status"] == "incomplete"
    assert sequence["producer"] == producer
    if producer != "solution":
        assert (repo / "src/thing.py").read_text() == "A = 3\n"
    from pathlib import Path

    path = Path(sequence["stages"][producer]["path"])
    assert "blocking" not in path.read_text()
    assert (
        events.read_text().splitlines()
        == ["solution", "fixer", "closer"][: ["solution", "fixer", "closer"].index(producer) + 1]
    )


@pytest.mark.parametrize(
    "guard", ["read-only", "conditional", "output", "disposition", "fix-publication", "closer"]
)
@pytest.mark.meta
def test_review_guard_detects_its_fault(tmp_path, monkeypatch, guard):
    import shutil

    from close_helpers import PLUGIN

    def guarantee(root):
        root.mkdir()
        if guard == "disposition":
            test_same_tree_green_retry_requires_lead_disposition(root)
        elif guard == "output":
            test_malformed_stage_preserves_work_and_names_producer(root, "solution")
        elif guard == "conditional":
            test_clean_review_skips_fix_and_close(root, "claude", "story")
        elif guard == "closer":
            test_remaining_problem_hands_back_without_relaunch(root, "closer-blocked")
        elif guard == "fix-publication":
            repo, env, _git, key, events, _hooks = flow_repo(root, scenario="fixed")
            binary = root / "bin/claude"
            text = binary.read_text().replace(
                "rc=subprocess.run(['git','commit','-qm','fix finding']).returncode", "rc=0"
            )
            binary.write_text(text)
            result = invoke(repo, env, key)
            assert result.returncode == 2
            assert events.read_text().splitlines() == ["solution", "fixer"]
            assert (repo / "src/thing.py").read_text() == "A = 3\n"
        else:
            repo, env, _git, key, _events, _hooks = flow_repo(root)
            binary = root / "bin/claude"
            text = binary.read_text().replace(
                "report={'blocking':[]}",
                "report={'blocking':[]}\nPath('src/thing.py').write_text('A = 9\\n')\n"
                "subprocess.run(['git','commit','-qam','forbidden reviewer edit'],check=True)",
            )
            binary.write_text(text)
            result = invoke(repo, env, key)
            assert result.returncode == 2
            assert (repo / "src/thing.py").read_text() == "A = 9\n"

    guarantee(tmp_path / "control")
    installed = tmp_path / "installed"
    shutil.copytree(PLUGIN, installed)
    path = installed / "scripts/close/review_sequence.py"
    text = path.read_text()
    if guard in ("read-only", "fix-publication"):
        text = text.replace("    if motion or error:", '    motion = ""\n    if motion or error:')
    elif guard == "closer":
        text = text.replace(
            'for name in ("solution", "fixer", "closer"):', 'for name in ("solution", "fixer"):'
        )
    elif guard == "conditional":
        text = text.replace(
            'if name != "solution" and not sequence["stages"]["solution"]["report"]["actionable"]:',
            "if False:",
        )
    elif guard == "output":
        path = installed / "scripts/review_report.py"
        text = path.read_text().replace(
            '    required = ("actionable", "blocking") if stage == "solution" else ("blocking",)',
            '    data.setdefault("blocking", [])\n    required = ()',
        )
    else:
        path = installed / "scripts/close/review_validation.py"
        text = path.read_text().replace(
            'if any(item["error"] for item in sequence["validation"]):', "if False:"
        )
    path.write_text(text)
    monkeypatch.setenv("XP_FLOW_TEST_CLOSE", str(installed / "scripts/close.py"))
    with pytest.raises(AssertionError):
        guarantee(tmp_path / "mutant")


@pytest.mark.parametrize("producer", ["solution", "fixer", "closer"])
def test_explicit_report_correction_keeps_completed_work(tmp_path, producer):
    from pathlib import Path

    repo, env, git, key, events, hooks = flow_repo(tmp_path, scenario="malformed-" + producer)
    assert invoke(repo, env, key).returncode == 2
    before = checkpoint(env, key)
    report = Path(before["stages"][producer]["path"])
    raw = report.read_bytes()
    head = git("rev-parse", "HEAD").stdout
    binary = tmp_path / "bin/claude"
    binary.write_text(
        binary.read_text()
        .replace("'malformed-" + producer + "'", "'fixed'")
        .replace(
            "if stage=='fixer':",
            "if stage=='fixer' and 'Correct only the incomplete report' not in prompt:",
        )
    )
    result = invoke(repo, env, key)
    assert result.returncode == 0, result.stderr
    assert report.read_bytes() == raw
    if producer != "solution":
        assert git("rev-parse", "HEAD").stdout == head
        assert hooks.read_text().splitlines() == ["hook"]
    names = events.read_text().splitlines()
    assert names.count("solution") == (2 if producer == "solution" else 1)
    assert names.count("fixer") == (2 if producer == "fixer" else 1)
    assert names.count("closer") == (2 if producer == "closer" else 1)


@pytest.mark.parametrize("scenario", ["clean", "fixed"])
def test_validation_kill_resumes_validation_only(tmp_path, monkeypatch, scenario):
    import os
    import signal
    import subprocess
    import sys
    import time
    from contextlib import chdir
    from pathlib import Path

    from close_helpers import CLOSE, SPAWN

    ready = tmp_path / "validation-started"
    finish = tmp_path / "validation-finish"
    gate = tmp_path / "gate"
    gate.write_text(
        f"#!/bin/sh\ntouch {ready}\nwhile [ ! -e {finish} ]; do sleep 0.1; done\necho finished\n"
    )
    gate.chmod(0o755)
    repo, env, git, key, events, _hooks = flow_repo(tmp_path, verify=str(gate), scenario=scenario)
    assert git("branch", "-m", "t/story-042-demo-story").returncode == 0
    branch = git("branch", "--show-current").stdout.strip()
    assert git("checkout", "-q", "main").returncode == 0
    tree = Path(env["XP_DATA"]) / "worktrees" / key
    tree.parent.mkdir()
    assert git("worktree", "add", str(tree), branch).returncode == 0
    from completion import inputs, record
    from plan_review import card_for

    with monkeypatch.context() as patch, chdir(tree):
        for name, value in env.items():
            patch.setenv(name, value)
        snapshot = inputs(key, card_for(key))
        for stage in ("executor", "story-tier", "reviewer"):
            record(key, stage, "running" if stage == "reviewer" else "ran", snapshot)
    process = subprocess.Popen(
        [sys.executable, str(CLOSE), "story", key, "review"],
        cwd=tree,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    try:
        deadline = time.monotonic() + 30
        while not ready.exists() and time.monotonic() < deadline:
            assert process.poll() is None
            time.sleep(0.02)
        assert ready.exists()
        old = checkpoint(env, key)
        assert old["status"] == "validation"
        saved = Path(old["stages"]["solution"]["path"]).read_bytes()
        os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=5)
        finish.touch()
        result = subprocess.run(
            [sys.executable, str(SPAWN), "resume", key],
            cwd=repo,
            env=env,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr
        expected = ["solution"] if scenario == "clean" else ["solution", "fixer", "closer"]
        assert events.read_text().splitlines() == expected
        assert Path(old["stages"]["solution"]["path"]).read_bytes() == saved
        assert checkpoint(env, key)["status"] == "completed"
        import json

        handoff = json.loads((Path(env["XP_DATA"]) / "plans" / f"{key}.handoff.json").read_text())
        from completion import next_stage

        with monkeypatch.context() as patch, chdir(tree):
            for name, value in env.items():
                patch.setenv(name, value)
            assert next_stage(key, handoff, inputs(key, card_for(key))) == "reviewer"
        reviewer = handoff["checkpoint"]["results"]["reviewer"]
        assert reviewer["result"] == "ran"
        assert reviewer["output"] == checkpoint(env, key)["output"]["inputs"]
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=5)
