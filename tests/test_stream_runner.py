import inspect
import json
import os
import subprocess
import sys
from pathlib import Path

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


def log_lines(tmp_path, log_id="story-042-review"):
    return (tmp_path / "data" / "logs" / f"{log_id}.log").read_text().splitlines()


def test_the_log_points_at_claudes_native_transcript_never_in_the_header(tmp_path, monkeypatch):
    """AC6. The header is written before any session id exists, so a pointer
    found THERE would be one the code invented rather than read off the stream."""
    from spawn import run_agent

    monkeypatch.setenv("XP_DATA", str(tmp_path / "data"))
    monkeypatch.setenv("HOME", str(tmp_path))
    run_agent(
        event_script(
            tmp_path,
            ['{"type":"system","session_id":"sess-9"}', '{"type":"result","result":"done"}'],
        ),
        tmp_path,
        "",
        "reviewer",
        "claude",
        "story-042-review",
    )
    header, first, pointer, *_ = log_lines(tmp_path)
    assert "sess-9" not in header and "transcript" not in header
    slug = "-" + str(tmp_path.resolve()).lstrip("/").replace("/", "-")
    assert pointer == f"transcript: {tmp_path / '.claude' / 'projects' / slug / 'sess-9.jsonl'}"
    assert "session_id" in first, "the pointer displaced the event it was read from"


def test_the_codex_pointer_resolves_the_rollout_and_says_so_when_it_cannot(tmp_path, monkeypatch):
    """`thread.started` is codex's FIRST event, so the rollout it names may not
    exist yet — the miss must read as a search, not as a path that never opens."""
    from spawn import run_agent

    monkeypatch.setenv("XP_DATA", str(tmp_path / "data"))
    monkeypatch.setenv("HOME", str(tmp_path))
    rollout = tmp_path / ".codex" / "sessions" / "2026" / "08" / "23"
    rollout.mkdir(parents=True)
    (rollout / "rollout-2026-08-23T01-00-00-thread-1.jsonl").write_text("{}\n")
    done = '{"type":"item.completed","item":{"type":"agent_message","text":"done"}}'
    for t, expected in (("thread-1", str(rollout)), ("thread-404", "not written yet")):
        stream = [f'{{"type":"thread.started","thread_id":"{t}"}}', done]
        run_agent(event_script(tmp_path, stream), tmp_path, "", "reviewer", "codex", f"{t}-review")
        pointer = [ln for ln in log_lines(tmp_path, f"{t}-review") if ln.startswith("transcript")]
        assert pointer and expected in pointer[0], pointer


def test_every_role_leaves_a_tee_d_log(tmp_path, monkeypatch):
    """AC4's second half, asserted positively: liveness is the SPAWNER's property,
    so no role may be the one whose run is a void."""
    from spawn import run_agent

    monkeypatch.setenv("XP_DATA", str(tmp_path / "data"))
    for role in ("reviewer", "plan-reviewer", "executor"):
        run_agent(
            event_script(tmp_path, ['{"type":"result","result":"done"}']),
            tmp_path,
            "",
            role,
            "claude",
            f"story-042-{role}",
        )
        assert (tmp_path / "data" / "logs" / f"story-042-{role}.log").exists(), role


def test_a_log_that_fails_on_its_FIRST_write_still_returns_the_result(tmp_path, monkeypatch):
    """AC1's fault injection at the one write outside tee_stream's OSError arm:
    the header. Disk-full between open and first write is the modelled failure,
    and an unguarded header turns it into `could not launch the reviewer` — the
    whole review lost to its own log."""
    import teammate_tee
    from spawn import run_agent

    class Dead:
        def write(self, _line):
            raise OSError("disk full")

        flush = close = lambda self: None

    monkeypatch.setenv("XP_DATA", str(tmp_path / "data"))
    monkeypatch.setattr(teammate_tee, "open", lambda *a, **k: Dead(), raising=False)
    proc = run_agent(
        event_script(tmp_path, ['{"type":"result","result":"survived"}']),
        tmp_path,
        "",
        "reviewer",
        "claude",
        "story-042-review",
    )
    assert json.loads(proc.stdout)["result"] == "survived"


def test_the_claude_slug_maps_dots_to_dashes_like_the_harness_does(tmp_path, monkeypatch):
    """MEASURED against ~/.claude/projects on this machine: a cwd holding a dot
    is slugged with that dot as a DASH — `/Users/x/.xp/data/…` lands under
    `-Users-x--xp-data-…`, correlated over ~90 recorded (cwd, slug) pairs. A
    `/`-only replace therefore names a file that never exists, and Sprint-5's
    own story-028 log points at one: worktrees live under the data root, `~/.xp`.
    A pointer that does not open is the whole failure this line exists to avoid."""
    from teammate_tee import _transcript_path

    monkeypatch.setenv("HOME", str(tmp_path))
    cwd = tmp_path / ".xp" / "data" / "proj.id" / "worktrees" / "story-042"
    slug = Path(_transcript_path("claude", cwd, "sess-1")).parent.name

    assert "." not in slug, slug
    assert slug.endswith("--xp-data-proj-id-worktrees-story-042"), slug


def test_a_codex_line_that_is_not_an_object_is_tolerated_not_raised(tmp_path, monkeypatch):
    """parse_stream_json's docstring promises an unparseable line is echoed as
    nothing, never raised, and its codex twin guards only the `item` lookup — so
    a bare `7` or `[]` on the stream reached `evt.get` and died with an
    AttributeError. It is raised from inside tee_stream's drain loop, where only
    OSError is caught, so ONE stray line loses the whole run and its review with
    it."""
    from teammate_tee import parse_codex_json, run_stream

    for line in ("7", '"a string"', "[]", "null"):
        assert parse_codex_json(line) == (None, None), line

    monkeypatch.setenv("XP_DATA", str(tmp_path / "data"))
    lines = ["7", '{"type":"item.completed","item":{"type":"agent_message","text":"done"}}']
    proc = run_stream(
        event_script(tmp_path, lines),
        tmp_path,
        "",
        "story-042-review",
        tmp_path / "data",
        "codex",
        dict(os.environ),
        out=lambda _l: None,
        err=lambda _l: None,
    )
    assert proc.returncode == 0 and proc.stdout == "done"


def test_the_LAST_codex_agent_message_is_the_result_not_the_first(tmp_path, monkeypatch):
    """MEASURED on 0.149.0 (walks/story-028-json-full-probe.jsonl): with tools in
    play codex emits MULTIPLE completed agent_messages per turn — an early
    narration and then the terminal answer. First-wins hands review.py the
    narration and records a round on prose no reviewer wrote. The rule was
    documented and unpinned: mutating tee_stream to first-wins left the full
    suite green."""
    from spawn import run_agent

    monkeypatch.setenv("XP_DATA", str(tmp_path / "data"))
    lines = [
        '{"type":"thread.started","thread_id":"t-1"}',
        '{"type":"item.completed","item":{"type":"agent_message","text":"narrating first"}}',
        '{"type":"item.completed","item":{"type":"command_execution","command":"pytest"}}',
        '{"type":"item.completed","item":{"type":"agent_message","text":"the real findings"}}',
        '{"type":"turn.completed","usage":{}}',
    ]
    proc = run_agent(
        event_script(tmp_path, lines), tmp_path, "", "reviewer", "codex", "story-042-review"
    )
    assert proc.returncode == 0
    assert proc.stdout == "the real findings"
