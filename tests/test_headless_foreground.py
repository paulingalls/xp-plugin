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


def launch_and_read_env(tmp_path, runner, monkeypatch, **kwargs):
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
        monkeypatch,
        story_id="free-test",
        data_root=tmp_path / "data",
        harness="claude",
    )
    assert [env[key] for key in BACKGROUND_ENV] == ["1", "3600000", "3600000"]


def test_claude_reviewer_child_gets_its_agent_bound(tmp_path, monkeypatch):
    from spawn import run_agent

    for key in BACKGROUND_ENV:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("XP_DATA", str(tmp_path / "data"))
    monkeypatch.setenv("XP_AGENT_TIMEOUT", "1.25")
    env = launch_and_read_env(
        tmp_path,
        run_agent,
        monkeypatch,
        role="reviewer",
        harness="claude",
        log_id="review",
    )
    assert [env[key] for key in BACKGROUND_ENV] == ["1", "1250", "1250"]


@pytest.mark.parametrize("kept", BACKGROUND_ENV)
def test_claude_child_keeps_each_explicit_background_value(tmp_path, monkeypatch, kept):
    from teammate_tee import run_stream

    env = {kept: "explicit"}
    received = launch_and_read_env(
        tmp_path,
        run_stream,
        monkeypatch,
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

    repo, env, _git = make_repo(tmp_path)
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


@pytest.mark.parametrize("mixed", [False, True])
def test_dirty_review_refusal_saves_one_applicable_combined_patch(tmp_path, monkeypatch, mixed):
    import review

    repo, head = git_repo(tmp_path, monkeypatch)
    (repo / "a.txt").write_text("a1\n")
    subprocess.run(["git", "add", "a.txt"], cwd=repo, check=True)
    if mixed:
        (repo / "b.txt").write_text("b1\n")
    text = review.abort_text(head, "dirty")
    patches = list((tmp_path / "data" / "reports").glob("review-refusal-*.patch"))
    assert len(patches) == 1 and patches[0].stat().st_size
    assert text.index(str(patches[0])) < text.index("git reset --hard")
    subprocess.run(["git", "reset", "--hard", head], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "apply", str(patches[0])], cwd=repo, check=True)
    assert (repo / "a.txt").read_text() == "a1\n"
    assert (repo / "b.txt").read_text() == ("b1\n" if mixed else "b0\n")


def test_each_dirty_refusal_allocates_a_new_patch(tmp_path, monkeypatch):
    import review

    repo, head = git_repo(tmp_path, monkeypatch)
    (repo / "a.txt").write_text("changed\n")
    subprocess.run(["git", "add", "a.txt"], cwd=repo, check=True)
    review.abort_text(head, "first")
    review.abort_text(head, "second")
    patches = list((tmp_path / "data" / "reports").glob("review-refusal-*.patch"))
    assert len(patches) == 2 and patches[0] != patches[1]
    subprocess.run(["git", "reset", "--hard", head], cwd=repo, check=True, capture_output=True)
    for patch in patches:
        subprocess.run(["git", "apply", "--check", str(patch)], cwd=repo, check=True)


def test_unwritable_reports_path_keeps_the_index_and_omits_reset(tmp_path, monkeypatch):
    import review

    repo, head = git_repo(tmp_path, monkeypatch)
    reports = tmp_path / "data" / "reports"
    reports.parent.mkdir(parents=True)
    reports.write_text("blocked")
    (repo / "a.txt").write_text("only copy\n")
    subprocess.run(["git", "add", "a.txt"], cwd=repo, check=True)
    before = subprocess.run(
        ["git", "diff", "--cached"], cwd=repo, capture_output=True, text=True
    ).stdout
    text = review.abort_text(head, "dirty")
    after = subprocess.run(
        ["git", "diff", "--cached"], cwd=repo, capture_output=True, text=True
    ).stdout
    assert "could not save" in text and "reset --hard" not in text
    assert before == after and reports.is_file()


@pytest.mark.parametrize("failure", ["git", "write"])
def test_failed_patch_creation_removes_partial_artifact_and_omits_reset(
    tmp_path, monkeypatch, failure
):
    import close
    import review
    import review_refusal

    repo, head = git_repo(tmp_path, monkeypatch)
    (repo / "a.txt").write_text("only copy\n")
    subprocess.run(["git", "add", "a.txt"], cwd=repo, check=True)
    if failure == "git":
        real_git = close.git

        def failing_git(*args, **kwargs):
            if args[0] == "diff-index":
                raise subprocess.CalledProcessError(1, args)
            return real_git(*args, **kwargs)

        monkeypatch.setattr(close, "git", failing_git)
    else:
        real_file = review_refusal.tempfile.NamedTemporaryFile

        class FailingFile:
            def __enter__(self):
                self.file = real_file(
                    "w", dir=tmp_path / "data" / "reports", suffix=".patch", delete=False
                )
                self.name = self.file.name
                return self

            def write(self, text):
                self.file.write(text[:5])
                self.file.flush()
                raise OSError("write failed")

            def __exit__(self, *_args):
                self.file.close()

        monkeypatch.setattr(
            review_refusal.tempfile, "NamedTemporaryFile", lambda *_args, **_kwargs: FailingFile()
        )
    text = review.abort_text(head, "dirty")
    assert "could not save" in text and "reset --hard" not in text
    assert list((tmp_path / "data" / "reports").glob("*.patch")) == []


def test_clean_review_refusal_text_and_reports_are_unchanged(tmp_path, monkeypatch):
    import review

    repo, head = git_repo(tmp_path, monkeypatch)
    assert review.abort_text(head, "why") == "refused: why"
    (repo / "a.txt").write_text("a1\n")
    subprocess.run(["git", "commit", "-qam", "move"], cwd=repo, check=True)
    expected = (
        f"refused: why\n\n a.txt | 2 +-\n 1 file changed, 1 insertion(+), 1 deletion(-)\n\n"
        f"No round was recorded. The reviewer's work is in your tree — yours to keep or undo:"
        f" git reset --hard {head[:8]}"
    )
    assert review.abort_text(head, "why") == expected
    assert not (tmp_path / "data" / "reports").exists()
