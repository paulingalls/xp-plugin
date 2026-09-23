"""Declare and measure ordered sprint full-tier legs."""

import time
from datetime import datetime, timezone
from pathlib import Path

from close import git
from work import config_block_value, strip_comment


def declared() -> tuple[list[tuple[str, str]] | None, str]:
    path = Path(".xp/config.yml")
    if not path.exists():
        return None, ""
    inside = False
    found = False
    names = []
    for raw in path.read_text(errors="replace").splitlines():
        line = strip_comment(raw)
        if line.rstrip() == "full_legs:":
            inside = True
            found = True
        elif inside and line.strip() and not line[:1].isspace():
            inside = False
        elif inside and line.strip():
            if ":" not in line:
                return None, "refused: malformed full_legs declaration"
            name = line.strip().split(":", 1)[0]
            if not name:
                return None, "refused: empty full_legs name"
            if name in names:
                return None, f"refused: duplicate full_legs name {name}"
            if name in ("land", "start"):
                return None, f"refused: reserved full_legs name {name}"
            names.append(name)
    if not names:
        return ([], "refused: full_legs has no commands") if found else (None, "")
    values = config_block_value("full_legs")
    legs = [(name, values[name]) for name in names]
    if any(not command for _, command in legs):
        return [], "refused: full_legs command is empty"
    joined = " && ".join(command for _, command in legs)
    tier = config_block_value("tests", "full")
    if joined != tier:
        return [], f"refused: full_legs join mismatch: tests.full={tier!r}; joined={joined!r}"
    return legs, ""


def inspect(ref: str, pending: bool) -> tuple[list[tuple[str, str]] | None, str]:
    current = Path(".xp/config.yml")
    if not pending and not current.exists():
        return None, ""
    if pending:
        local = current.read_text(errors="replace") if current.exists() else ""
        incoming = git("show", f"{ref}:.xp/config.yml", check=False).stdout
        if "full_legs:" not in local and "full_legs:" not in incoming:
            return None, ""
    staged = git("merge", "--no-commit", "--no-ff", ref, check=False) if pending else None
    try:
        if staged is not None and staged.returncode:
            return None, f"refused: merging {ref} here conflicts. Resolve and review again"
        return declared()
    finally:
        if staged is not None:
            git("merge", "--abort", check=False)


def latest(history: list[dict], name: str, command: str, tree: str) -> dict | None:
    return next(
        (
            item
            for item in reversed(history)
            if (item["leg"], item["command"], item["tree"]) == (name, command, tree)
        ),
        None,
    )


def run(legs, tier, tree, where, history, record_attempt, after_full):
    import overlap

    head = git("rev-parse", "HEAD").stdout.strip()
    components = []
    for name, command in legs:
        previous = latest(history, name, command, tree)
        reusable = previous is not None and previous["outcome"] in ("passed", "reused")
        start = datetime.now(timezone.utc)
        begin = time.monotonic()
        if reusable:
            rc = 0
            measured_head = previous["head"]
            status = "reused"
        else:
            print(f"full tier leg {name}: running {command}")
            rc = overlap._returncode(command)
            measured_head = head
            status = "ran"
        if rc == 127:
            return (
                f"refused: test tier leg {name} could not run{where}: {command}"
                " — nothing was measured or recorded; fix where it runs, then land again",
                None,
            )
        if rc < 0:
            return (
                f"refused: test tier leg {name} interrupted by signal {-rc}{where}: "
                f"{command} — nothing was measured or recorded; run land again"
            ), None
        outcome = "reused" if reusable else ("failed" if rc else "passed")
        component = {"leg": name, "command": command, "status": status, "head": measured_head}
        components.append(component)
        receipt = None
        if not rc and len(components) == len(legs):
            receipt = {
                "tier": "full",
                "command": tier,
                "tree": tree,
                "head": head,
                "verdict": "passed",
                "ran_by": "land",
                "reused": all(c["status"] == "reused" for c in components),
                "components": components,
            }
        end = max(start, datetime.now(timezone.utc))
        event = {
            "leg": name,
            "outcome": outcome,
            "command": command,
            "tree": tree,
            "head": measured_head,
            "started_at": start.isoformat().replace("+00:00", "Z"),
            "ended_at": end.isoformat().replace("+00:00", "Z"),
            "duration_seconds": max(0.0, time.monotonic() - begin),
        }
        if record_attempt and (red := record_attempt(event, receipt)):
            return red, None
        history.append(event)
        print(f"full tier leg {name}: {status} {command}")
        if rc:
            shown = overlap._red(f"test tier leg {name}", command, rc, where)
            return (after_full(shown) or shown) if after_full else shown, None
    if after_full and (red := after_full("")):
        return red, None
    return "", receipt
