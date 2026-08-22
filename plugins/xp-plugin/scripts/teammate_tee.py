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
    return summarize_event(evt), (evt if evt.get("type") == "result" else None)


def parse_plain(line: str) -> tuple[str | None, dict | None]:
    """Codex: prose, echoed as-is. `codex exec --json` exists, but its event
    vocabulary is unmeasured on 0.147.0 and measuring it means spawning codex —
    a summarizer against a guessed schema is a guess that compiles."""
    return line, None


# (per-line parse, does this harness's stream carry a terminal result object?)
STREAMS: dict[str, tuple[Callable[[str], tuple[str | None, dict | None]], bool]] = {
    "claude": (parse_stream_json, True),
    "codex": (parse_plain, False),
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
    legitimately outruns any wall clock (spawn.py's PERMISSION_ARGV comment).

    stdin is fed on its own thread — the prompt can exceed the pipe buffer,
    and writing it inline before reading stdout would deadlock a child that
    starts producing output before it has finished reading stdin.
    """
    parse, carries_result = STREAMS[harness]
    proc = subprocess.Popen(
        argv,
        cwd=cwd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env=os.environ | {"XP_ROLE": "teammate"},
    )
    feeder = threading.Thread(target=_feed_stdin, args=(proc, prompt))
    feeder.start()
    assert proc.stdout is not None
    with open(log_path(data_root, story_id), "a") as log:

        def log_write(line: str) -> None:
            log.write(line)
            log.flush()

        log_write(spawn_header(story_id, datetime.now(timezone.utc).isoformat(timespec="seconds")))
        result = tee_stream(proc.stdout, log_write, out, parse)
    feeder.join()
    proc.wait()
    if result is None:
        # Only where the harness promises one. On codex the exit code is the
        # whole in-band verdict, which is why spawn.py re-checks the TREE.
        if carries_result:
            err(f"{story_id}: the teammate's stream never carried a terminal result object")
            return proc.returncode or 1
        return proc.returncode
    out(closing_line(story_id, result))
    return proc.returncode
