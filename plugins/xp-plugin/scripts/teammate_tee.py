#!/usr/bin/env python3
"""Tee a spawned agent's output: verbatim to a durable log, a compact line to
stdout. EVERY role runs through here — liveness is the spawner's property.

One drain, two stream shapes — only the per-line parse and whether the stream
carries a terminal result object differ by harness."""

import contextlib
import json
import os
import subprocess
import sys
import threading
from collections.abc import Callable, Iterable
from datetime import datetime, timezone
from pathlib import Path

LogWrite = Callable[[str], None]
OutWrite = Callable[[str], None]


def spawn_header(story_id: str, iso_ts: str) -> str:
    return f"===== spawn {story_id} {iso_ts} =====\n"


def log_path(data_root: Path, log_id: str) -> Path:
    """One spelling for every role's log, beside the teammate's, where the lead
    already knows to tail. The caller makes the directory: it is the caller that
    has somewhere to put the failure."""
    return data_root / "logs" / f"{log_id}.log"


def summarize_event(evt: dict) -> str:
    """One compact line for a parsed stream-json object."""
    kind = evt.get("type", "?")
    if kind in ("assistant", "user"):
        blocks = (evt.get("message") or {}).get("content") or []
        kinds = [b.get("type", "?") for b in blocks if isinstance(b, dict)]
        return f"[{kind}] {','.join(kinds) or 'text'}"
    if kind == "result":
        return "[result] " + ("error" if evt.get("is_error") else "ok")
    if kind == "system":
        return f"[system] {evt.get('subtype', '')}".rstrip()
    return f"[{kind}]"


def parse_stream_json(line: str) -> tuple[str | None, dict | None]:
    """(what to echo, the terminal result object if this line is it). An
    unparseable line is tolerated — echoed as nothing, not raised."""
    try:
        evt = json.loads(line)
    except ValueError:
        return None, None
    if not isinstance(evt, dict):
        return None, None
    return summarize_event(evt), (evt if evt.get("type") == "result" else None)


def parse_codex_json(line: str) -> tuple[str | None, dict | None]:
    """`codex exec --json`, measured on 0.149.0. Codex has no result ENVELOPE, so
    the last completed `agent_message` is the terminal value — later ones win, the
    same rule the claude leg applies to its result event."""
    try:
        evt = json.loads(line)
    except ValueError:
        return None, None
    if not isinstance(evt, dict):
        return None, None
    item = evt.get("item") if isinstance(evt.get("item"), dict) else {}
    completed = evt.get("type") == "item.completed"
    terminal = evt if completed and item.get("type") == "agent_message" else None
    return f"[{evt.get('type', '?')}] {item.get('type', '')}".rstrip(), terminal


# (per-line parse, does this harness's stream carry a terminal result object?)
STREAMS: dict[str, tuple[Callable[[str], tuple[str | None, dict | None]], bool]] = {
    "claude": (parse_stream_json, True),
    "codex": (parse_codex_json, True),
}


def tee_stream(
    lines: Iterable[str],
    log_write: LogWrite,
    out_write: OutWrite,
    parse: Callable[[str], tuple[str | None, dict | None]] = parse_stream_json,
) -> dict | None:
    """Drain `lines` fully no matter what `log_write` does — ceasing to drain
    deadlocks a healthy child writing to a full pipe.
    """
    result = None
    for line in lines:
        try:
            log_write(line)
        except OSError as e:
            out_write(f"warning: log write failed ({e}); continuing without it")
        stripped = line.strip()
        if not stripped:
            continue
        echo, evt = parse(stripped)
        if echo is not None:
            out_write(echo)
        if evt is not None:
            result = evt
    return result


def closing_line(story_id: str, result: dict) -> str:
    turns = result.get("num_turns", "?")
    duration = result.get("duration_ms")
    duration_s = f"{duration / 1000:.1f}s" if isinstance(duration, int | float) else "?"
    cost = result.get("total_cost_usd")
    cost_s = f"${cost:.2f}" if isinstance(cost, int | float) else "?"
    status = "ERROR" if result.get("is_error") else "ok"
    return f"{story_id}: {turns} turns, {duration_s}, {cost_s}, {status}"


def _feed_stdin(proc: subprocess.Popen, prompt: str) -> None:
    """A child that dies before consuming the prompt breaks this pipe. That is
    not news — the missing result object already says it — and an unhandled
    exception in a thread buries that diagnosis under a traceback."""
    assert proc.stdin is not None
    with contextlib.suppress(BrokenPipeError):
        try:
            proc.stdin.write(prompt)
        finally:
            proc.stdin.close()


def _session_id(harness: str, line: str) -> str:
    """The harness's own id for this run, off the first event that carries one:
    claude stamps `session_id` on every event, codex `thread_id` on
    `thread.started`, which it emits first."""
    try:
        evt = json.loads(line)
    except ValueError:
        return ""
    if not isinstance(evt, dict):
        return ""
    return str(evt.get("session_id" if harness == "claude" else "thread_id") or "")


def _result_text(harness: str, result: dict) -> str:
    """What the caller reads. Claude's whole envelope, because review.py wants
    its `result` key and closing_line its counters; codex has no envelope, so
    the terminal agent_message's text IS the result."""
    if harness == "claude":
        return json.dumps(result)
    return str((result.get("item") or {}).get("text", ""))


def _transcript_path(harness: str, cwd: Path, session: str) -> str:
    """A POINTER at the harness's own archive, which is richer than our tee.
    Claude's path is computable; codex names its rollout after a start timestamp
    we never see, so it is searched — and `thread.started` is the FIRST event, so
    the file may not exist yet. A miss returns the SEARCH, never a path that does
    not resolve: a pointer that silently does not open is worse than none."""
    home = Path.home()
    if harness == "claude":
        # `.` dashes too, measured over ~90 recorded (cwd, slug) pairs under
        # ~/.claude/projects: a `/`-only slug missed every worktree, ours included
        # (they live under the data root, `~/.xp`).
        slug = "-" + str(cwd.resolve()).lstrip("/").replace("/", "-").replace(".", "-")
        return str(home / ".claude" / "projects" / slug / f"{session}.jsonl")
    root = home / ".codex" / "sessions"
    pattern = f"rollout-*-{session}.jsonl"
    found = next(root.rglob(pattern), None)
    return str(found) if found else f"(not written yet) {root}/*/*/*/{pattern}"


def run_stream(
    argv: list[str],
    cwd: Path,
    prompt: str,
    log_id: str,
    data_root: Path,
    harness: str,
    env: dict,
    timeout: float | None = None,
    out: OutWrite = print,
    err: OutWrite = lambda s: print(s, file=sys.stderr),
) -> subprocess.CompletedProcess:
    """EVERY spawned agent, whatever its role: stream live, tee to a durable log,
    reassemble the harness's terminal result so the caller reads what the old
    captured run handed it.

    stdin is fed on its own thread — the prompt can exceed the pipe buffer, and
    writing it inline before draining stdout would deadlock a child that starts
    producing output before it has finished reading stdin.
    """
    parse, carries_result = STREAMS[harness]
    if argv[:2] == ["codex", "exec"]:
        # HERE, not at one caller: while the widening lived in run_agent alone the
        # teammate leg launched without it, and the codex teammate that could not
        # commit was this story's own author.
        from spawn import common_dir_widening  # spawn imports us; local breaks the cycle

        if widen := common_dir_widening(cwd):
            argv = [*argv[:-1], *widen, argv[-1]]  # before the trailing stdin `-`
    proc = subprocess.Popen(
        argv,
        cwd=cwd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env=env,
    )
    feeder = threading.Thread(target=_feed_stdin, args=(proc, prompt))
    feeder.start()
    timed_out = threading.Event()

    def kill() -> None:
        # poll FIRST: a timer that fires as the last line lands would otherwise
        # throw away a run that finished, and the review it carried with it.
        if proc.poll() is None:
            timed_out.set()
            proc.kill()

    timer = threading.Timer(timeout, kill) if timeout is not None else None
    if timer:
        timer.start()
    path = log_path(data_root, log_id)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        log = open(path, "a")  # noqa: SIM115 — the no-log fallback has no file to enter
    except OSError as exc:
        err(f"warning: log open failed ({exc}); continuing without it")
        log = None
    else:
        # review.py used to announce the launch here; a run that STREAMS needs the
        # path instead, and naming it in the runner names it for every role.
        err(f"live log: {path}")
    pointed = False

    def log_write(line: str) -> None:
        nonlocal pointed
        if not log:
            return
        log.write(line)
        if not pointed and (session := _session_id(harness, line.strip())):
            log.write(f"transcript: {_transcript_path(harness, cwd, session)}\n")
            pointed = True
        log.flush()

    result = None
    try:
        # The header alone is outside tee_stream's OSError arm, and it is written
        # before any session id exists — which is why the pointer is never in it.
        try:
            stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
            log_write(spawn_header(log_id, stamp))
        except OSError as exc:
            err(f"warning: log write failed ({exc}); continuing without it")
        assert proc.stdout is not None
        result = tee_stream(proc.stdout, log_write, out, parse)
    finally:
        if timer:
            timer.cancel()
        feeder.join()
        proc.wait()
        if log:
            log.close()
    if timed_out.is_set():
        raise subprocess.TimeoutExpired(argv, timeout, stderr=str(path))
    rc = proc.returncode
    if result is None and carries_result:
        err(f"{log_id}: stream never carried a terminal result; see {path}")
        rc = rc or 1
    return subprocess.CompletedProcess(
        argv,
        rc,
        _result_text(harness, result) if result else "",
        "" if rc == 0 else f"see live log: {path}",
    )


def run_teammate(
    argv: list[str],
    cwd: Path,
    prompt: str,
    story_id: str,
    data_root: Path,
    harness: str = "claude",
    out: OutWrite = print,
    err: OutWrite = lambda s: print(s, file=sys.stderr),
) -> int:
    """The teammate leg's thin wrapper: no timeout, because a teammate
    legitimately outruns any wall clock (spawn.run_agent's timeout comment)."""
    proc = run_stream(
        argv,
        cwd,
        prompt,
        story_id,
        data_root,
        harness,
        os.environ | {"XP_ROLE": "teammate"},
        out=out,
        err=err,
    )
    if proc.returncode == 0 and harness == "claude" and proc.stdout:
        out(closing_line(story_id, json.loads(proc.stdout)))
    return proc.returncode
