import inspect
import json
import subprocess
import sys

import pytest


def event_script(tmp_path, lines, pause=0):
    path = tmp_path / "events.py"
    path.write_text(
        "import sys, time\n"
        + "\n".join(f"print({line!r}); sys.stdout.flush()" for line in lines)
        + (f"\ntime.sleep({pause})" if pause else "")
        + "\n"
    )
    return [sys.executable, str(path)]


def test_run_agent_signature_has_harness_and_log_id_not_capture():
    from spawn import run_agent

    names = inspect.signature(run_agent).parameters
    assert "capture" not in names
    assert "harness" in names and "log_id" in names


@pytest.mark.parametrize(
    ("harness", "lines", "expected"),
    [
        ("claude", ['{"type":"result","result":"claude done"}'], "claude done"),
        (
            "codex",
            [
                '{"type":"thread.started","thread_id":"thread-1"}',
                '{"type":"item.started","item":{"type":"agent_message","text":"wrong"}}',
                '{"type":"item.completed","item":{"type":"agent_message","text":"codex done"}}',
            ],
            "codex done",
        ),
    ],
)
def test_reviewer_stream_reassembles_result_and_writes_log(
    tmp_path, monkeypatch, harness, lines, expected
):
    from spawn import run_agent

    data = tmp_path / "data"
    monkeypatch.setenv("XP_DATA", str(data))
    proc = run_agent(
        event_script(tmp_path, lines), tmp_path, "", "reviewer", harness, "story-042-review"
    )
    assert proc.returncode == 0
    value = json.loads(proc.stdout)["result"] if harness == "claude" else proc.stdout
    assert value == expected
    assert (data / "logs" / "story-042-review.log").exists()


def test_stream_without_terminal_result_is_loud(tmp_path, monkeypatch):
    from spawn import run_agent

    monkeypatch.setenv("XP_DATA", str(tmp_path / "data"))
    proc = run_agent(
        event_script(tmp_path, ['{"type":"turn.completed"}']),
        tmp_path,
        "",
        "reviewer",
        "codex",
        "story-042-review",
    )
    assert proc.returncode == 1
    assert "log" in proc.stderr


def test_reviewer_watchdog_kills_a_quiet_stream(tmp_path, monkeypatch):
    from spawn import run_agent

    monkeypatch.setenv("XP_DATA", str(tmp_path / "data"))
    monkeypatch.setenv("XP_AGENT_TIMEOUT", "0.1")
    with pytest.raises(subprocess.TimeoutExpired) as caught:
        run_agent(
            event_script(tmp_path, ['{"type":"system","session_id":"s"}'], pause=5),
            tmp_path,
            "",
            "reviewer",
            "claude",
            "story-042-review",
        )
    assert "story-042-review.log" in str(caught.value.stderr)


def test_log_open_failure_does_not_lose_the_result(tmp_path, monkeypatch):
    from spawn import run_agent

    data = tmp_path / "data"
    data.mkdir()
    (data / "logs").write_text("blocks mkdir")
    monkeypatch.setenv("XP_DATA", str(data))
    proc = run_agent(
        event_script(tmp_path, ['{"type":"result","result":"still done"}']),
        tmp_path,
        "",
        "reviewer",
        "claude",
        "story-042-review",
    )
    assert json.loads(proc.stdout)["result"] == "still done"


def test_cardless_sprint_review_gets_scoped_log(tmp_path, monkeypatch):
    import review
    from close_helpers import make_repo

    repo, env, _g = make_repo(tmp_path)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    monkeypatch.chdir(repo)
    result, error = review.run(
        f"REPORT_PATH: {tmp_path / 'report.json'}\n", repo, name="sprint release"
    )
    assert result and not error
    assert (tmp_path / "data" / "logs" / "sprint-release-review.log").exists()
