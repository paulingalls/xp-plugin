"""Nonfatal timing ledger and sprint wall-clock report."""

import fcntl
import itertools
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


def utc_now():
    return datetime.now(timezone.utc)


class Span:
    def __init__(self, root: Path, kind: str, name: str):
        self.root, self.kind, self.name = root, kind, name
        self.start = utc_now()
        self.tick = time.monotonic()

    def finish(self, outcome: str):
        path = self.root / "timing.jsonl"
        event = {
            "kind": self.kind,
            "name": self.name,
            "started_at": self.start.isoformat(),
            "ended_at": utc_now().isoformat(),
            "duration_seconds": max(time.monotonic() - self.tick, 1e-9),
            "outcome": outcome,
        }
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(f"{path}.lock", "a+") as lease:
                fcntl.flock(lease, fcntl.LOCK_EX)
                with path.open("a") as stream:
                    stream.write(json.dumps(event) + "\n")
        except OSError as exc:
            print(f"warning: timing ledger {path} write failed: {exc}", file=sys.stderr)


def _date(value):
    stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if stamp.utcoffset() != timezone.utc.utcoffset(stamp):
        raise ValueError(f"timestamp is not UTC: {value}")
    return stamp


def release_start(root: Path):
    records = []
    for path in (root / "releases").glob("*.json"):
        record = json.loads(path.read_text())
        if "released_at" in record:
            stamp = _date(record["released_at"])
        elif tag := record.get("tag"):
            result = subprocess.run(
                ["git", "for-each-ref", "--format=%(creatordate:iso-strict)", f"refs/tags/{tag}"],
                capture_output=True,
                text=True,
            )
            if result.returncode or not result.stdout.strip():
                raise ValueError(f"release record {path} tag {tag} has no creation date")
            stamp = _date(result.stdout.strip())
        else:
            raise ValueError(f"release record {path} has no released_at or tag")
        records.append(stamp)
    return max(records) if records else None


def table(root: Path, tier_history=()) -> str:
    start = release_start(root)
    events = []
    path = root / "timing.jsonl"
    if path.exists():
        for number, line in enumerate(path.read_text().splitlines(), 1):
            try:
                events.append(json.loads(line))
            except ValueError as exc:
                raise ValueError(f"unreadable timing ledger line {number}: {exc}") from exc
    for item in tier_history:
        events.append({"kind": "full-tier", "name": item["command"], **item})
    rows = []
    for item in events:
        begin, end = _date(item["started_at"]), _date(item["ended_at"])
        if end < begin:
            raise ValueError(f"timing interval ends before it starts: {item}")
        if start is None or begin > start:
            rows.append((begin, end, item))
    rows.sort(key=lambda row: (row[0], row[1]))
    label = start.isoformat() if start else "no release yet — all events"
    lines = [f"Timing since {label}"]
    for begin, end, item in rows:
        lines.append(
            f"{item['kind']} | {item['name']} | {begin.isoformat()} → {end.isoformat()}"
            f" | {item['outcome']} | {(end - begin).total_seconds():.1f}s"
        )
    if not rows:
        return "\n".join([*lines, "CALENDAR 0.0s", "ACTIVE 0.0s"])
    merged = []
    for begin, end, _ in rows:
        if merged and begin <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((begin, end))
    for left, right in itertools.pairwise(merged):
        gap = (right[0] - left[1]).total_seconds()
        if gap > 600:
            lines.append(f"idle — awaiting human or CI (not distinguished): {gap:.1f}s")
    calendar = (max(end for _, end, _ in rows) - rows[0][0]).total_seconds()
    active = sum((end - begin).total_seconds() for begin, end in merged)
    return "\n".join([*lines, f"CALENDAR {calendar:.1f}s", f"ACTIVE {active:.1f}s"])
