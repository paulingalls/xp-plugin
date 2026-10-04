"""The two commands the plugin runs for a project: a card's Acceptance and the sprint hook."""

import os
import shlex
import subprocess
import sys
from pathlib import Path

from xpcore.config import data_root, refuse

PUNCTUATION = "();<>|&"


def split_commands(line: str) -> list[list[str]]:
    """`a && b` into argvs. No shell: anything else a shell would interpret is refused."""
    lexer = shlex.shlex(line, posix=True, punctuation_chars=PUNCTUATION)
    lexer.whitespace_split = True
    try:
        tokens = list(lexer)
    except ValueError as exc:
        refuse(f"Acceptance {line!r} does not parse ({exc}); fix the card's Acceptance: line")
    commands: list[list[str]] = [[]]
    for token in tokens:
        if token == "&&":
            commands.append([])
        elif token and set(token) <= set(PUNCTUATION):
            refuse(
                f"Acceptance {line!r} uses {token!r}; only `&&` chains commands here,"
                " so put anything else in a script and name the script"
            )
        else:
            commands[-1].append(token)
    if not all(commands):
        refuse(f"Acceptance {line!r} has an empty command; fix the card's Acceptance: line")
    return commands


def stream(argv: list[str], cwd, log) -> int:
    """Echo live and tee verbatim; the log is what the refusal points at."""
    log.write(f"$ {shlex.join(argv)}\n")
    log.flush()
    try:
        proc = subprocess.Popen(
            argv, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
        )
    except OSError as exc:
        log.write(f"{exc}\n")
        print(exc, file=sys.stderr)
        return 127
    assert proc.stdout is not None
    for line in proc.stdout:
        sys.stdout.write(line)
        log.write(line)
    log.flush()
    return proc.wait()


def log_path(log_id: str) -> Path:
    path = data_root() / "logs" / f"{log_id}.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def run_acceptance(commands: list[list[str]], cwd, log_id: str) -> int:
    with open(log_path(log_id), "a") as log:
        for argv in commands:
            if rc := stream(argv, cwd, log):
                return rc
    return 0


def sprint_hook(root: Path) -> list[str]:
    if (root / "lefthook.yml").is_file():
        return ["lefthook", "run", "sprint"]
    script = root / ".githooks" / "sprint"
    if script.is_file() and os.access(script, os.X_OK):
        return [str(script)]
    refuse(
        f"no sprint hook in {root}: neither lefthook.yml (`lefthook run sprint`) nor an"
        " executable .githooks/sprint; run xp.py setup, or add one of them"
    )


def run_sprint_hook(root: Path, log_id: str) -> int:
    argv = sprint_hook(root)
    with open(log_path(log_id), "a") as log:
        return stream(argv, root, log)
