"""Detached review process and incomplete-marker lifecycle."""

import json
import os
import shlex
import subprocess
import sys
import time
from pathlib import Path

from close import fail
from env import sprint_id_value
from work import data_root

POLL_SECONDS = 3
LOG_TAIL = 2000
ACTIVITY_NOUN = {"slate": "slate review", "plan": "plan review", "refresh": "card refresh"}


def safe_story_id(identifier: str) -> str:
    if not identifier or Path(identifier).name != identifier or identifier in (".", ".."):
        raise ValueError(f"refused: {identifier!r} is not a safe story id")
    return identifier


def review_findings_path(identifier: str, kind: str) -> Path:
    identifier = safe_story_id(identifier)
    parent = data_root() / ("plans" if kind in ("plan", "refresh") else "slate-reviews")
    if kind == "plan":
        stem = identifier
    elif kind == "refresh":
        stem = f"{identifier}.refresh"
    else:
        stem = f"sprint-{identifier}"
    legacy = parent / f"{stem}.md"
    rounds = [1] if legacy.exists() else []
    prefix = f"{stem}.round-"
    if parent.is_dir():
        for path in parent.iterdir():
            name = path.name
            if name.startswith(prefix) and name.endswith(".md"):
                encoded = name[len(prefix) : -3]
                if encoded.isdecimal() and int(encoded) > 0 and encoded == str(int(encoded)):
                    rounds.append(int(encoded))
    return parent / f"{stem}.round-{max(rounds, default=0) + 1}.md"


def review_marker(identifier: str, kind: str) -> Path:
    """Use session recovery's sprint spelling so absence remains a success signal."""
    identifier = safe_story_id(identifier)
    suffix = "plan-review-incomplete"
    if kind != "plan":
        suffix = f"{'card-refresh' if kind == 'refresh' else 'slate-review'}-incomplete"
    return data_root() / "markers" / f"{sprint_id_value(identifier)}.{suffix}"


def _marker_state(identifier: str, kind: str) -> dict:
    try:
        return json.loads(review_marker(identifier, kind).read_text())
    except (OSError, ValueError):
        return {}


def _running(identifier: str, kind: str) -> tuple[Path, int] | None:
    state = _marker_state(identifier, kind)
    pid, out = state.get("pid"), state.get("findings")
    if not (pid and out):
        return None
    try:
        os.kill(int(pid), 0)
    except (OSError, ValueError):
        return None
    return Path(out), int(pid)


def run_detached(identifier: str, kind: str, out: Path, argv: list[str]) -> int:
    if running := _running(identifier, kind):
        running_out, pid = running
        print(f"joining the {ACTIVITY_NOUN[kind]} already running (pid {pid})", file=sys.stderr)
        return _wait(identifier, kind, running_out, pid)
    out.parent.mkdir(parents=True, exist_ok=True)
    pid, child = _detach(identifier, kind, out, argv)
    return _wait(identifier, kind, out, pid, child)


def _detach(identifier: str, kind: str, out: Path, argv: list[str]) -> tuple[int, subprocess.Popen]:
    identifier = safe_story_id(identifier)
    log = data_root() / "logs" / f"{identifier}-{ACTIVITY_NOUN[kind].replace(' ', '-')}.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    marker = review_marker(identifier, kind)
    marker.parent.mkdir(parents=True, exist_ok=True)
    # Shipped scripts are not executable, so a pasteable retry needs `python3`.
    next_command = shlex.join(["python3", *argv])
    marker.write_text(
        json.dumps(
            {
                "findings": str(out),
                "log": str(log),
                "state": f"{ACTIVITY_NOUN[kind].upper()} DID NOT COMPLETE",
                "next": f"run {next_command} again to join or restart it",
            }
        )
    )
    handle = open(log, "a")  # noqa: SIM115 — the detached child owns it
    child = subprocess.Popen(
        [sys.executable, *argv, "--_review", str(out)],
        cwd=Path.cwd(),
        stdout=handle,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
    )
    # Do not recreate a marker a fast child already removed as its success signal.
    if state := _marker_state(identifier, kind):
        marker.write_text(json.dumps(state | {"pid": child.pid}))
    print(f"{ACTIVITY_NOUN[kind]} running (pid {child.pid}); live log: {log}", file=sys.stderr)
    return child.pid, child


def _wait(
    identifier: str,
    kind: str,
    out: Path,
    pid: int,
    child: subprocess.Popen | None = None,
) -> int:
    while not _dead(pid, child):
        time.sleep(POLL_SECONDS)
    marker = review_marker(identifier, kind)
    state = _marker_state(identifier, kind)
    if marker.exists():
        if refusal := state.get("refusal"):
            return fail(refusal)
        try:
            tail = Path(state.get("log", "")).read_text(errors="replace")[-LOG_TAIL:].strip()
        except OSError:
            tail = ""
        action = state.get("next", f"run the {ACTIVITY_NOUN[kind]} again")
        log = state.get("log", "(no log)")
        return fail(
            f"{tail}\n(the {ACTIVITY_NOUN[kind]} ended without a verdict; full output in"
            f" {log}; {action})"
        )
    if kind == "refresh":
        import slate_review

        return slate_review._refresh_handoff(identifier, out)
    print(out.read_text().strip() if out.is_file() else "")
    handoff = (
        "read the disposition and re-read the reviewed plan before coding"
        if kind == "plan"
        else "read every finding before accepting or rejecting its conclusion"
    )
    print(f"findings: {out.resolve()} — {handoff}", file=sys.stderr)
    return 0


def _dead(pid: int, child: subprocess.Popen | None) -> bool:
    if child is not None:
        return child.poll() is not None
    try:
        os.kill(pid, 0)
    except OSError:
        return True
    return False
