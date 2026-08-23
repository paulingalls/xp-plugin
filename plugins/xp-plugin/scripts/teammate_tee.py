#!/usr/bin/env python3
"""Tee a teammate's output: verbatim to a durable log, a compact line to stdout.

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


def log_path(data_root: Path, story_id: str) -> Path:
    d = data_root / "logs"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{story_id}.log"


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
    return summarize_event(evt), (evt if evt.get("type") == "result" or "result" in evt else None)


def parse_codex_json(line: str) -> tuple[str | None, dict | None]:
    try:
        evt = json.loads(line)
    except ValueError:
        return None, None
    item = evt.get("item", {}) if isinstance(evt, dict) else {}
    completed = evt.get("type") == "item.completed"
    terminal = evt if completed and item.get("type") == "agent_message" else None
    return f"[{evt.get('type', '?')}]", terminal


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


def _session_id(harness: str, event: dict) -> str:
    if harness == "codex" and event.get("type") == "thread.started":
        return str(event.get("thread_id", ""))
    if harness == "claude" and event.get("type") == "system":
        return str(event.get("session_id", ""))
    return ""


def _result_text(harness: str, result: dict) -> str:
    if harness == "claude":
        return json.dumps(result)
    return str((result.get("item") or {}).get("text", ""))


def _transcript_path(harness: str, cwd: Path, session: str) -> str:
    home = Path.home()
    if harness == "claude":
        slug = "-" + str(cwd.resolve()).lstrip("/").replace("/", "-")
        return str(home / ".claude" / "projects" / slug / f"{session}.jsonl")
    root = home / ".codex" / "sessions"
    fallback = root / f"**/rollout-*-{session}.jsonl"
    return str(next(root.rglob(f"rollout-*-{session}.jsonl"), fallback))


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
    parse, carries_result = STREAMS[harness]
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
        timed_out.set()
        proc.kill()

    timer = threading.Timer(timeout, kill) if timeout is not None else None
    if timer:
        timer.start()
    path = data_root / "logs" / f"{log_id}.log"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        log = open(path, "a")  # noqa: SIM115 — conditional fallback has no file to enter
    except OSError as exc:
        err(f"warning: log open failed ({exc}); continuing without it")
        log = None
    result = None
    pointer_written = False

    def write(line: str) -> None:
        if log:
            log.write(line)
            log.flush()

    try:
        write(spawn_header(log_id, datetime.now(timezone.utc).isoformat(timespec="seconds")))
        assert proc.stdout is not None
        for line in proc.stdout:
            try:
                write(line)
            except OSError as exc:
                err(f"warning: log write failed ({exc}); continuing without it")
            stripped = line.strip()
            echo, terminal = parse(stripped) if stripped else (None, None)
            if echo is not None:
                out(echo)
            if terminal is not None:
                result = terminal
            if not pointer_written and stripped:
                try:
                    session = _session_id(harness, json.loads(stripped))
                except (ValueError, TypeError):
                    session = ""
                if session:
                    write(f"transcript: {_transcript_path(harness, cwd, session)}\n")
                    pointer_written = True
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
    """Launch the teammate, stream its output live. No timeout: a teammate
    legitimately outruns any wall clock (spawn.run_agent's timeout comment).

    stdin is fed on its own thread — the prompt can exceed the pipe buffer,
    and writing it inline before reading stdout would deadlock a child that
    starts producing output before it has finished reading stdin.
    """
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
