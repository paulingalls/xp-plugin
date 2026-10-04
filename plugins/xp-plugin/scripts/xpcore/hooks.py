"""The two commands the plugin runs for a project: a card's Acceptance and the sprint hook."""

import os
import shlex
import subprocess
import sys
from pathlib import Path

from xpcore.config import LEFTHOOK_CONFIGS, data_root, refuse


def stream(argv: list[str], cwd, log, env: dict[str, str] | None = None) -> int:
    """Echo live and tee verbatim; the log is what the refusal points at."""
    log.write(f"$ {shlex.join(argv)}\n")
    log.flush()
    try:
        proc = subprocess.Popen(
            argv, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env
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


def run_acceptance(line: str, cwd, log_id: str) -> int:
    """The card's line, as a shell would run it from the repo root; its exit code is the
    verdict. The agents that write cards have that shell already."""
    with open(log_path(log_id), "a") as log:
        return stream(["sh", "-c", line], cwd, log)


def sprint_hook(root: Path) -> list[str]:
    if any((root / name).is_file() for name in LEFTHOOK_CONFIGS):
        return ["lefthook", "run", "sprint"]
    script = root / ".githooks" / "sprint"
    if script.is_file() and os.access(script, os.X_OK):
        return [str(script)]
    refuse(
        f"no sprint hook in {root}: neither a lefthook config (`lefthook run sprint`) nor an"
        " executable .githooks/sprint; run xp.py setup, or add one of them"
    )


def run_sprint_hook(root: Path, log_id: str) -> int:
    """LEFTHOOK=0 or LEFTHOOK_EXCLUDE in the lead's shell makes lefthook exit 0 having run
    nothing; the release suite must not inherit either."""
    argv = sprint_hook(root)
    env = {k: v for k, v in os.environ.items() if not k.startswith("LEFTHOOK")}
    with open(log_path(log_id), "a") as log:
        return stream(argv, root, log, env)
