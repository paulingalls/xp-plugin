import json
import os
import subprocess
import sys

import pytest
from close_helpers import make_repo

BACKGROUND_ENV = (
    "CLAUDE_CODE_DISABLE_BACKGROUND_TASKS",
    "BASH_DEFAULT_TIMEOUT_MS",
    "BASH_MAX_TIMEOUT_MS",
)
DIAGNOSTIC = "background task killed when the headless run exited"


def event_script(tmp_path, events, exit_code=0, record=None):
    path = tmp_path / f"events-{len(list(tmp_path.glob('events-*')))}.py"
    recording = f"open({str(record)!r}, 'w').write(json.dumps(dict(os.environ)))" if record else ""
    path.write_text(
        "import json, os, sys\n"
        f"{recording}\n"
        f"events = {events!r}\n"
        "for item in events: print(json.dumps(item), flush=True)\n"
        f"sys.exit({exit_code})\n"
    )
    return [sys.executable, str(path)]


def claude_result(value="done"):
    return {"type": "result", "is_error": False, "result": value}


def launch_and_read_env(tmp_path, runner, **kwargs):
    recorded = tmp_path / "child-env.json"
    argv = event_script(tmp_path, [claude_result()], record=recorded)
    runner(argv=argv, cwd=tmp_path, prompt="", **kwargs)
    return json.loads(recorded.read_text())


def test_claude_executor_child_gets_default_foreground_environment(tmp_path, monkeypatch):
    from teammate_tee import run_teammate

    for key in BACKGROUND_ENV:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("XP_AGENT_TIMEOUT", "0.01")
    env = launch_and_read_env(
        tmp_path,
        run_teammate,
        story_id="free-test",
        data_root=tmp_path / "data",
        harness="claude",
    )
    assert [env[key] for key in BACKGROUND_ENV] == ["1", "14400000", "14400000"]


@pytest.mark.parametrize("agent_timeout, bound", [("1.25", "1250"), (None, "14400000")])
def test_claude_reviewer_child_gets_its_agent_bound(tmp_path, monkeypatch, agent_timeout, bound):
    from spawn import run_agent

    for key in BACKGROUND_ENV:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("XP_DATA", str(tmp_path / "data"))
    if agent_timeout is None:
        monkeypatch.delenv("XP_AGENT_TIMEOUT", raising=False)
    else:
        monkeypatch.setenv("XP_AGENT_TIMEOUT", agent_timeout)
    env = launch_and_read_env(
        tmp_path,
        run_agent,
        role="reviewer",
        harness="claude",
        log_id="review",
    )
    assert [env[key] for key in BACKGROUND_ENV] == ["1", bound, bound]


@pytest.mark.parametrize("kept", BACKGROUND_ENV)
def test_claude_child_keeps_each_explicit_background_value(tmp_path, monkeypatch, kept):
    from teammate_tee import run_stream

    env = {kept: "explicit"}
    received = launch_and_read_env(
        tmp_path,
        run_stream,
        log_id="claude",
        data_root=tmp_path / "data",
        harness="claude",
        env=env,
    )
    assert received[kept] == "explicit"
    assert all(key in received for key in BACKGROUND_ENV)


@pytest.mark.parametrize("preset", [False, True])
def test_codex_child_environment_is_not_decorated(tmp_path, monkeypatch, preset):
    from teammate_tee import run_stream

    recorded = tmp_path / "codex-env.json"
    env = {"SENTINEL": "kept"}
    if preset:
        env[BACKGROUND_ENV[0]] = "explicit"
    events = [{"type": "item.completed", "item": {"type": "agent_message", "text": "done"}}]
    proc = run_stream(
        event_script(tmp_path, events, record=recorded),
        tmp_path,
        "",
        "codex",
        tmp_path / "data",
        "codex",
        env,
    )
    received = json.loads(recorded.read_text())
    assert proc.returncode == 0 and received["SENTINEL"] == "kept"
    assert {key for key in BACKGROUND_ENV if key in received} == (
        {BACKGROUND_ENV[0]} if preset else set()
    )


def task_start(task_id, description, backgrounded):
    return {
        "type": "system",
        "subtype": "task_started",
        "task_id": task_id,
        "description": description,
        "is_backgrounded": backgrounded,
    }


def task_update(task_id, **patch):
    return {"type": "system", "subtype": "task_updated", "task_id": task_id, "patch": patch}


def run_claude(tmp_path, events, exit_code=0):
    from teammate_tee import run_stream

    return run_stream(
        event_script(tmp_path, events, exit_code),
        tmp_path,
        "",
        "claude",
        tmp_path / "data",
        "claude",
        dict(os.environ),
    )


@pytest.mark.parametrize("patched", [False, True])
@pytest.mark.parametrize("exit_code", [0, 7])
def test_killed_background_task_is_reported_without_changing_status(tmp_path, patched, exit_code):
    events = [task_start("one", "verify the change", not patched)]
    if patched:
        events.append(task_update("one", is_backgrounded=True))
    events += [claude_result(), task_update("one", status="killed")]
    proc = run_claude(tmp_path, events, exit_code)
    assert proc.returncode == exit_code
    assert json.loads(proc.stdout)["result"] == "done"
    assert DIAGNOSTIC in proc.stderr and "verify the change" in proc.stderr


def test_only_the_first_killed_background_task_is_reported_and_bounded(tmp_path):
    long_name = "FIRST-" + "x" * 500
    events = [
        task_start("one", long_name, True),
        task_start("two", "SECOND-TASK", True),
        claude_result(),
        task_update("one", status="killed"),
        task_update("two", status="killed"),
    ]
    proc = run_claude(tmp_path, events)
    first = proc.stderr.splitlines()[0]
    assert first.startswith(DIAGNOSTIC) and "FIRST-" in first and first.endswith("…")
    assert len(first) < 300 and "SECOND-TASK" not in proc.stderr
    assert proc.stderr.index(DIAGNOSTIC) < proc.stderr.index("see live log:")


@pytest.mark.parametrize(
    "events",
    [
        [
            task_start("one", "completed", True),
            claude_result(),
            task_update("one", status="completed"),
        ],
        [
            task_start("one", "foreground", False),
            claude_result(),
            task_update("one", status="killed"),
        ],
        [
            task_start("one", "unknown", True),
            claude_result(),
            task_update("other", status="killed"),
        ],
        [
            task_start("one", "notification", True),
            claude_result(),
            {
                "type": "system",
                "subtype": "task_notification",
                "task_id": "one",
                "status": "stopped",
            },
        ],
        [task_start("one", "unterminated", True), claude_result()],
        [
            task_start("one", "finally completed", True),
            claude_result(),
            task_update("one", status="killed"),
            task_update("one", status="completed"),
        ],
        [
            task_start("one", "agent stopped", True),
            task_update("one", status="killed"),
            {
                "type": "system",
                "subtype": "task_notification",
                "task_id": "one",
                "status": "stopped",
            },
            claude_result(),
        ],
    ],
)
def test_non_killed_task_states_have_no_background_failure_diagnostic(tmp_path, events):
    proc = run_claude(tmp_path, events)
    assert proc.returncode == 0 and json.loads(proc.stdout)["result"] == "done"
    assert DIAGNOSTIC not in proc.stderr


@pytest.mark.parametrize("exit_code", [0, 7])
def test_review_run_preserves_its_decision_while_reporting_exit_kill(
    tmp_path, monkeypatch, capsys, exit_code
):
    import review
    import spawn

    caller = tmp_path / "caller"
    (caller / ".xp").mkdir(parents=True)
    (caller / ".xp/config.yml").write_text("roles:\n  reviewer: codex/gpt-6.1-sol/medium\n")
    monkeypatch.chdir(caller)
    repo, env, _git = make_repo(tmp_path)
    monkeypatch.chdir(repo)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    events = [
        task_start("one", "review verification", True),
        claude_result("findings"),
        task_update("one", status="killed"),
    ]
    monkeypatch.setattr(
        spawn, "agent_argv", lambda *_args: event_script(tmp_path, events, exit_code)
    )
    result, error = review.run("prompt", repo, checked=True)
    emitted = capsys.readouterr().err
    if exit_code == 0:
        assert (result, error) == ("findings", "")
        assert "review verification" in emitted
    else:
        assert result == "" and error.startswith("reviewer exited 7:")
        assert DIAGNOSTIC in error[:500] and "review verification" in error[:500]


def git_repo(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True)
    (repo / "a.txt").write_text("a0\n")
    (repo / "b.txt").write_text("b0\n")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=repo, check=True)
    monkeypatch.chdir(repo)
    monkeypatch.setenv("XP_DATA", str(tmp_path / "data"))
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()
    return repo, head


@pytest.mark.parametrize("before, after", [(b"a\r\nb\r\n", b"a\r\nB\r\n"), (b"\xe9\n", b"\xe9!\n")])
def test_refusal_preserves_staged_and_unstaged_bytes(tmp_path, monkeypatch, before, after):
    import review

    repo, head = git_repo(tmp_path, monkeypatch)
    (repo / "a.txt").write_bytes(before)
    subprocess.run(["git", "add", "a.txt"], cwd=repo, check=True)
    (repo / "a.txt").write_bytes(after)
    (repo / "new.txt").write_bytes(after)
    text = review.abort_text(head, "dirty")
    staged = subprocess.run(
        ["git", "show", ":a.txt"], cwd=repo, check=True, capture_output=True
    ).stdout
    assert staged == before
    assert (repo / "a.txt").read_bytes() == after
    assert (repo / "new.txt").read_bytes() == after
    assert "reset --hard" not in text
    assert not (tmp_path / "data" / "reports").exists()
