"""Falsify a plan review's raised close-review depth reaching the story reviewer."""

import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

CLOSE = Path(__file__).parents[2] / "plugins" / "xp-plugin" / "scripts" / "close.py"
CARD = (
    "# plan\n#### story-042 — depth   [in-progress]\n"
    "Files: a.py\nAC:\n- a\nVerify: true\nClose review: standard\n"
)
DEEP = re.compile(r"^Close review:\s*deep\b", re.M)


def red(why: str) -> int:
    print(why, file=sys.stderr)
    return 1


def prompt_outside_charter(tmp: Path, drafted: str) -> tuple[int, str]:
    """The charter itself quotes `Close review: deep`, so only what follows it counts."""
    data = tmp / "data"
    (data / "plans").mkdir(parents=True, exist_ok=True)
    (data / "plan.md").write_text(CARD)
    (data / "plans" / "story-042.plan.md").write_text(
        f"# story-042 execution plan\n\nClose review: {drafted}\n\nReason: assigned by the plan"
        " reviewer.\n"
    )
    env = os.environ | {"XP_DATA": str(data), "PATH": f"{tmp / 'bin'}:/usr/bin:/bin"}
    shown = subprocess.run(
        [sys.executable, str(CLOSE), "story", "story-042", "review", "--dry-run"],
        cwd=tmp / "repo",
        env=env,
        capture_output=True,
        text=True,
    )
    after = shown.stdout.split("## Your report", 1)
    return shown.returncode, (after[1] if len(after) == 2 else "") + shown.stderr


def main() -> int:
    with tempfile.TemporaryDirectory() as folder:
        tmp = Path(folder)
        (tmp / "bin").mkdir()
        (tmp / "bin" / "claude").write_text(
            "#!/bin/sh\n"
            'echo \'[{"id":"xp-plugin@xp-plugin","version":"fixture","scope":"user"}]\'\n'
        )
        (tmp / "bin" / "claude").chmod(0o755)
        repo = tmp / "repo"
        (repo / ".xp").mkdir(parents=True)
        who = {"GIT_AUTHOR_NAME": "l", "GIT_AUTHOR_EMAIL": "l@x"}
        env = os.environ | who | {"GIT_COMMITTER_NAME": "l", "GIT_COMMITTER_EMAIL": "l@x"}
        g = lambda *a: subprocess.run(["git", *a], cwd=repo, env=env, capture_output=True)  # noqa: E731
        g("init", "-q", "-b", "main")
        (repo / ".xp" / "config.yml").write_text("trunk: main\nroles:\n  reviewer: claude/opus\n")
        (repo / ".xp" / "constraints.md").write_text("# Constraints\n1. C\n")
        (repo / ".xp" / "system.md").write_text("# System\nS\n")
        (repo / "a.py").write_text("A = 1\n")
        g("add", "-A")
        g("commit", "-qm", "base")
        g("checkout", "-qb", "story-042")
        (repo / "a.py").write_text("A = 2\n")
        g("commit", "-qam", "story work")

        rc, control = prompt_outside_charter(tmp, "standard")
        if rc or "## Story card" not in control:
            return red(f"the dry-run review printed no prompt (rc={rc}): {control[-400:]}")
        if DEEP.search(control):
            return red("a standard plan review already reads deep: this check cannot red")
        rc, raised = prompt_outside_charter(tmp, "deep")
        if rc or not DEEP.search(raised):
            return red(
                "a plan review that raised Close review to deep never reached the story"
                f" reviewer's prompt; the card still says standard (rc={rc})"
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
