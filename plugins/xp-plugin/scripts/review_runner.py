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
from log_rotate import open_log
from log_rotate import tail as log_tail
from work import data_root

POLL_SECONDS = 3
LOG_TAIL = 2000
ACTIVITY_NOUN = {"slate": "slate review", "plan": "plan review", "refresh": "card refresh"}
REVIEW_ROUND_CAP = 2


def safe_story_id(identifier: str) -> str:
    if not identifier or Path(identifier).name != identifier or identifier in (".", ".."):
        raise ValueError(f"refused: {identifier!r} is not a safe story id")
    return identifier


def _round_location(identifier: str, kind: str) -> tuple[Path, str]:
    identifier = safe_story_id(identifier)
    parent = data_root() / ("plans" if kind in ("plan", "refresh") else "slate-reviews")
    if kind == "plan":
        stem = identifier
    elif kind == "refresh":
        stem = f"{identifier}.refresh"
    else:
        stem = f"sprint-{identifier}"
    return parent, stem


def review_rounds(identifier: str, kind: str) -> list[tuple[int, Path]]:
    parent, stem = _round_location(identifier, kind)
    legacy = parent / f"{stem}.md"
    rounds = []
    prefix = f"{stem}.round-"
    if parent.is_dir():
        for path in parent.iterdir():
            name = path.name
            if name.startswith(prefix) and name.endswith(".md"):
                encoded = name[len(prefix) : -3]
                if (
                    path.is_file()
                    and encoded.isdecimal()
                    and int(encoded) > 0
                    and encoded == str(int(encoded))
                ):
                    rounds.append((int(encoded), path))
    if legacy.is_file() and not any(number == 1 for number, _path in rounds):
        rounds.append((1, legacy))
    return sorted(rounds)


def review_findings_path(identifier: str, kind: str) -> Path:
    parent, stem = _round_location(identifier, kind)
    rounds = review_rounds(identifier, kind)
    if incomplete := _incomplete_round(identifier, kind, rounds):
        return incomplete
    return parent / f"{stem}.round-{max((n for n, _p in rounds), default=0) + 1}.md"


def _incomplete_round(identifier: str, kind: str, rounds: list[tuple[int, Path]]) -> Path | None:
    state = _marker_state(identifier, kind)
    if state.get("disposition") == "blocked" or (
        kind == "slate" and state.get("disposition") == "slate-verdict"
    ):
        return None
    findings = state.get("findings")
    if not isinstance(findings, str):
        return None
    candidate = Path(findings).resolve()
    return next((path for _number, path in rounds if path.resolve() == candidate), None)


def completed_review_rounds(identifier: str, kind: str) -> list[tuple[int, Path]]:
    rounds = review_rounds(identifier, kind)
    incomplete = _incomplete_round(identifier, kind, rounds)
    return [(number, path) for number, path in rounds if path != incomplete]


def review_prior(identifier: str, kind: str) -> tuple[str, str]:
    rendered = []
    for number, path in completed_review_rounds(identifier, kind):
        try:
            body = path.read_text()
        except OSError as error:
            return "", f"refused: cannot read prior round {number} at {path}: {error}"
        rendered.append(f"### Round {number}\n\n{body.rstrip()}")
    return "\n\n".join(rendered), ""


def review_is_capped(identifier: str, kind: str) -> bool:
    return len(completed_review_rounds(identifier, kind)) >= REVIEW_ROUND_CAP


def archive_review_rounds(identifier: str, kind: str, label: str = "superseded") -> str:
    rounds = review_rounds(identifier, kind)
    if not rounds:
        return ""
    parent, stem = _round_location(identifier, kind)
    generation = 1
    while any(
        (parent / f"{stem}.{label}-{generation}.round-{number}.md").exists()
        for number, _path in rounds
    ):
        generation += 1
    targets = [
        parent / f"{stem}.{label}-{generation}.round-{number}.md" for number, _path in rounds
    ]
    try:
        for (_number, path), target in zip(rounds, targets, strict=True):
            path.replace(target)
    except OSError as error:
        return f"refused: cannot archive review rounds: {error}"
    return ""


def archive_failed_findings(out: Path) -> str:
    if not out.is_file():
        return ""
    generation = 1
    target = out.with_name(f"{out.stem}.failed-{generation}{out.suffix}")
    while target.exists():
        generation += 1
        target = out.with_name(f"{out.stem}.failed-{generation}{out.suffix}")
    try:
        out.replace(target)
    except OSError as error:
        return f"; could not preserve failed findings outside the round count: {error}"
    return ""


def review_marker(identifier: str, kind: str) -> Path:
    """Use session recovery's sprint spelling so absence remains a success signal."""
    identifier = safe_story_id(identifier)
    suffix = "plan-review-incomplete"
    if kind != "plan":
        suffix = f"{'card-refresh' if kind == 'refresh' else 'slate-review'}-incomplete"
    return data_root() / "markers" / f"{sprint_id_value(identifier)}.{suffix}"


def _marker_state(identifier: str, kind: str) -> dict:
    try:
        state = json.loads(review_marker(identifier, kind).read_text())
        return state if isinstance(state, dict) else {}
    except (OSError, UnicodeError, ValueError):
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


def slate_review_pid(identifier: str) -> int | None:
    pid = _marker_state(identifier, "slate").get("pid")
    if type(pid) is not int or pid <= 0:
        return None
    try:
        os.kill(pid, 0)
    except OSError:
        return None
    return pid


def run_detached(identifier: str, kind: str, out: Path, argv: list[str]) -> int:
    if running := _running(identifier, kind):
        running_out, pid = running
        print(f"joining the {ACTIVITY_NOUN[kind]} already running (pid {pid})", file=sys.stderr)
        return _wait(identifier, kind, running_out, pid, argv)
    out.parent.mkdir(parents=True, exist_ok=True)
    pid, child = _detach(identifier, kind, out, argv)
    return _wait(identifier, kind, out, pid, argv, child)


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
    log_available = True
    try:
        handle, lease = open_log(log)
    except OSError as exc:
        log_available = False
        print(f"warning: log open failed ({exc}); continuing without it", file=sys.stderr)
        handle, lease = open(os.devnull, "w"), None  # noqa: SIM115 — child owns it
    try:
        child = subprocess.Popen(
            [sys.executable, *argv, "--_review", str(out)],
            cwd=Path.cwd(),
            stdout=handle,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
            pass_fds=(lease.fileno(),) if lease else (),
        )
    finally:
        handle.close()
        if lease:
            lease.close()
    # Do not recreate a marker a fast child already removed as its success signal.
    if state := _marker_state(identifier, kind):
        marker.write_text(json.dumps(state | {"pid": child.pid}))
    detail = f"live log: {log}" if log_available else "log unavailable"
    print(f"{ACTIVITY_NOUN[kind]} running (pid {child.pid}); {detail}", file=sys.stderr)
    return child.pid, child


def _wait(
    identifier: str,
    kind: str,
    out: Path,
    pid: int,
    argv: list[str],
    child: subprocess.Popen | None = None,
) -> int:
    while not _dead(pid, child):
        time.sleep(POLL_SECONDS)
    marker = review_marker(identifier, kind)
    state = _marker_state(identifier, kind)
    if marker.exists():
        if refusal := state.get("refusal"):
            if kind == "slate" and state.get("disposition") == "slate-verdict":
                marker.unlink(missing_ok=True)
            return fail(refusal)
        try:
            tail = log_tail(Path(state.get("log", "")), LOG_TAIL).strip()
        except OSError:
            tail = ""
        action = f"run {shlex.join(['python3', *argv])} again to join or restart it"
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
