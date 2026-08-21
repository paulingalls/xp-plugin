#!/usr/bin/env python3
"""Tee a teammate's stream-json output: verbatim to a durable log, a compact
line per event to stdout.

Extracted from spawn.py at story-017 (the split ../xp-agents made for the same
reason): the loop plus its parsing pushed spawn.py over the per-file cap.
"""

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
    """One compact line for a parsed stream-json object. Every recognised shape
    gets a line — the summary must never be the thing that goes silent."""
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


def tee_stream(lines: Iterable[str], log_write: LogWrite, out_write: OutWrite) -> dict | None:
    """Drain `lines` fully no matter what `log_write` does — ceasing to drain
    deadlocks a healthy child writing to a full pipe. Returns the terminal
    `type == "result"` object, or None if the stream never carried one.

    Unparseable lines are logged (verbatim, above) and skipped here — that is
    not an error; a stream with no terminal result object is the only one.
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
        try:
            evt = json.loads(stripped)
        except ValueError:
            continue
        if not isinstance(evt, dict):
            continue
        out_write(summarize_event(evt))
        if evt.get("type") == "result":
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
    assert proc.stdin is not None
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
    out: OutWrite = print,
    err: OutWrite = lambda s: print(s, file=sys.stderr),
) -> int:
    """Launch the teammate, stream its output live. No timeout: a teammate
    legitimately outruns any wall clock (spawn.py's PERMISSION_ARGV comment).

    stdin is fed on its own thread — the prompt can exceed the pipe buffer,
    and writing it inline before reading stdout would deadlock a child that
    starts producing output before it has finished reading stdin.
    """
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
    path = log_path(data_root, story_id)
    header = spawn_header(story_id, datetime.now(timezone.utc).isoformat(timespec="seconds"))
    with open(path, "a") as log:
        log.write(header)

        def log_write(line: str) -> None:
            log.write(line)
            log.flush()

        result = tee_stream(proc.stdout, log_write, out)
    feeder.join()
    proc.wait()
    if result is None:
        err(f"{story_id}: the teammate's stream never carried a terminal result object")
        return proc.returncode or 1
    out(closing_line(story_id, result))
    return proc.returncode
