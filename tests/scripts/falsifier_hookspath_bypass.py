"""Falsifier for the core.hooksPath bypass (record a8195145): reds if the
pre-push wall stops re-checking what a skipped pre-commit would have caught.

A hooksPath override leaves NO TRACE in the commit, so the ACT is unverifiable
after the fact — the only defence is checking the OUTCOME. That works here and
only here because every commit-stage gate is a pure function of the tree: ruff
and gitleaks re-run at push answer the same question about the same bytes. A
gate whose check is not reconstructible from the final state would be silently
bypassable forever (note 0f7d68c2).

CONSTRUCTED, never grepped: a real repo, a real ruff violation, a commit made
with core.hooksPath pointed at a directory that does not exist, and this
project's own lefthook.yml driving `lefthook run pre-push` over the result.
Greps of lefthook.yml would green the day the stanza is renamed.
"""

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).parents[2]


def main(tmp: Path) -> int:
    if not shutil.which("lefthook"):
        print("lefthook absent — cannot construct the condition", file=sys.stderr)
        return 1
    run = lambda *a, **k: subprocess.run(a, cwd=tmp, capture_output=True, text=True, **k)  # noqa: E731
    run("git", "init", "-q", "-b", "main")
    run("git", "config", "user.email", "lead@xp.local")
    run("git", "config", "user.name", "the lead")
    shutil.copy(REPO / "lefthook.yml", tmp / "lefthook.yml")
    (tmp / "pyproject.toml").write_text("[tool.ruff]\n")
    # The OTHER pre-push gates must PASS, or this reds on a missing ratchet
    # rather than on the bypass — measured: it did, and passed vacuously.
    stub = tmp / "tests" / "scripts"
    stub.mkdir(parents=True)
    (stub / "ratchet.py").write_text("raise SystemExit(0)\n")
    (tmp / "clean.py").write_text("A = 1\n")
    run("git", "add", "-A")
    run("git", "commit", "-qm", "base")

    # ruff rejects an unused import; the commit skips every hook by pointing
    # core.hooksPath at a directory that does not exist — git says nothing.
    (tmp / "sneaked.py").write_text("import os\n")
    run("git", "add", "-A")
    bypassed = run("git", "-c", "core.hooksPath=/nonexistent-hooks", "commit", "-qm", "sneaked")
    if bypassed.returncode != 0:
        print("the bypass itself failed; the condition was never built", file=sys.stderr)
        return 1

    walled = run("lefthook", "run", "pre-push")
    if walled.returncode == 0:
        print(
            "pre-push PASSED a tree carrying a violation pre-commit would have"
            " refused — a hooksPath bypass now reaches the remote unchecked",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as t:
        sys.exit(main(Path(t)))
