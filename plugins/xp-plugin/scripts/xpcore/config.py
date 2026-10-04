"""Where a project's state lives, what its .xp/config.yml says, and how a refusal reads."""

import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import NoReturn

HARNESSES = ("claude", "codex")
# Four seats are required; the optional ones fall back along their family, so a project
# can put one kind of review or fix on another harness without naming every seat.
ROLE_FALLBACK = {
    "plan-reviewer": "reviewer",
    "slate-reviewer": "plan-reviewer",
    "angle-reviewer": "reviewer",
    "fixer": "executor",
}
SETUP = "run `python3 <plugin>/scripts/xp.py setup` in the repo root"


LEFTHOOK_CONFIGS = (
    "lefthook.yml",
    ".lefthook.yml",
    "lefthook.yaml",
    "lefthook.toml",
    "lefthook.json",
)


def refuse(msg: str) -> NoReturn:
    """A precondition the lead can fix; the message ends by naming the next action."""
    print(f"refused: {msg}", file=sys.stderr)
    raise SystemExit(2)


def fail(msg: str) -> NoReturn:
    """Something ran and went wrong; the message names where to read."""
    print(f"failed: {msg}", file=sys.stderr)
    raise SystemExit(1)


def _git_value(*args: str) -> str:
    proc = subprocess.run(["git", *args], capture_output=True, text=True)
    if proc.returncode != 0:
        refuse(f"not inside a git repository ({os.getcwd()}); cd into the project repo first")
    return proc.stdout.strip()


def data_root() -> Path:
    if env := os.environ.get("XP_DATA"):
        return Path(env).expanduser()
    common = _git_value("rev-parse", "--path-format=absolute", "--git-common-dir")
    # The common dir, not the toplevel: every worktree of one repo shares one root.
    project = hashlib.sha256(os.path.realpath(common).encode()).hexdigest()[:12]
    return Path.home() / ".xp" / "data" / project


def plugin_root() -> Path:
    return Path(__file__).resolve().parents[2]


def repo_root() -> Path:
    return Path(_git_value("rev-parse", "--show-toplevel"))


def _scalar(raw: str):
    value = raw.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
        return value[1:-1]
    if re.fullmatch(r"-?\d+", value):
        return int(value)
    if re.fullmatch(r"-?\d+\.\d*", value):
        return float(value)
    return value


def parse_config(text: str, source: str = ".xp/config.yml") -> dict:
    """`key: value` and one-level maps; `#` starts a comment at line start or after a space."""
    config: dict = {}
    section: dict | None = None
    for number, line in enumerate(text.splitlines(), 1):
        body = re.sub(r"(^|\s)#.*$", "", line).rstrip()
        if not body.strip():
            continue
        match = re.fullmatch(r"(\s*)([\w.-]+):(?:\s+(.*))?", body)
        if not match:
            refuse(f"{source} line {number} is not `key: value`; fix that line")
        indent, key, value = match.groups()
        if indent:
            if section is None:
                refuse(f"{source} line {number} is indented under no map; fix that line")
            section[key] = _scalar(value or "")
        elif value:
            config[key], section = _scalar(value), None
        else:
            config[key] = section = {}
    return config


def load_config() -> dict:
    path = repo_root() / ".xp" / "config.yml"
    if not path.is_file():
        refuse(f"no {path}; {SETUP}")
    return parse_config(path.read_text(), str(path))


def role(name: str, override: str = "") -> tuple[str, str, str]:
    """(harness, model, effort) from `harness/model[/effort]`; a card's Executor: line overrides."""
    spec, seat = override.strip(), name
    if not spec:
        roles = load_config().get("roles") or {}
        while not (spec := str(roles.get(seat) or "")) and seat in ROLE_FALLBACK:
            seat = ROLE_FALLBACK[seat]
    if not spec:
        refuse(f"no role {seat!r} under roles: in .xp/config.yml; add `{seat}: claude/opus`")
    parts = spec.split("/")
    if len(parts) not in (2, 3) or not all(parts) or parts[0] not in HARNESSES:
        refuse(
            f"role {name} is {spec!r}, not harness/model[/effort] with harness"
            f" {' or '.join(HARNESSES)}; fix it in .xp/config.yml or the card's Executor: line"
        )
    return parts[0], parts[1], parts[2] if len(parts) == 3 else ""


def trunk() -> str:
    if configured := load_config().get("trunk"):
        return str(configured)
    proc = subprocess.run(
        ["git", "symbolic-ref", "--short", "refs/remotes/origin/HEAD"],
        capture_output=True,
        text=True,
    )
    if proc.returncode == 0 and proc.stdout.strip():
        return proc.stdout.strip().removeprefix("origin/")
    return "main"


def sprint_branch_name(identifier) -> str:
    return f"sprint-{str(identifier).lstrip('0').zfill(3)}"


def _sprint_branch_path() -> Path:
    return data_root() / "sprint_branch"


def sprint_branch() -> str:
    try:
        return _sprint_branch_path().read_text().strip()
    except FileNotFoundError:
        return ""


def record_sprint_branch(branch: str) -> None:
    recorded = sprint_branch()
    if recorded and recorded != branch:
        refuse(f"sprint branch {recorded} is still open; land it (xp.py sprint post-merge) first")
    path = _sprint_branch_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(branch + "\n")


def clear_sprint_branch() -> None:
    _sprint_branch_path().unlink(missing_ok=True)
