"""Run a project's optional unreceipted environment check."""

import subprocess
import sys
import time

from lifecycle import _commands


def prepare(raw: str) -> tuple[str, list[list[str]], str]:
    if not raw:
        return "", [], ""
    try:
        commands = _commands(raw, "preflight", runnable=True, chained=True)
    except ValueError as exc:
        return raw, [], str(exc)
    return raw, commands, ""


def preview(raw: str) -> str:
    return f"would run preflight: {raw}" if raw else ""


def run(raw: str, commands: list[list[str]]) -> str:
    if not raw:
        return ""
    start = time.monotonic()
    for argv in commands:
        sys.stdout.flush()
        sys.stderr.flush()
        try:
            result = subprocess.run(argv)
        except OSError as exc:
            return f"refused: preflight command {raw!r} could not run ({exc}); nothing was recorded"
        if result.returncode:
            return (
                f"refused: preflight command {raw!r} exited with exit code"
                f" {result.returncode}; nothing was recorded"
            )
    elapsed = time.monotonic() - start
    print(f"preflight: {elapsed:.1f}s", flush=True)
    if elapsed > 60:
        print("warning: preflight exceeded 60s", flush=True)
    return ""


def check(raw: str) -> str:
    if not raw:
        return ""
    raw, commands, error = prepare(raw)
    if error:
        return error
    before = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True).stdout
    if error := run(raw, commands):
        return error
    after = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True).stdout
    if after != before:
        return (
            "refused: preflight left the working tree dirty — commit or discard these"
            " changes, then retry; checks must judge the intended tree:\n  " + after.strip()
        )
    return ""
