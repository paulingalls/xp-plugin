"""Falsify per-clone sprint routing, fallback, and refusal boundaries."""

import contextlib
import io
import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[2] / "plugins" / "xp-plugin" / "scripts"))


def red(why: str) -> int:
    """A batch falsifier that reds in silence names no next action: the refusal
    and the bug it files carry this stderr, and nothing else explains the red."""
    print(why, file=sys.stderr)
    return 1


def refused(call) -> str:
    error = io.StringIO()
    with contextlib.redirect_stderr(error):
        try:
            call()
        except SystemExit as exc:
            if exc.code == 2:
                return error.getvalue()
    return ""


def main() -> int:
    import close

    with tempfile.TemporaryDirectory() as folder:
        tmp = Path(folder)
        (tmp / ".xp").mkdir()
        run = lambda *a: subprocess.run(a, cwd=tmp, check=True, capture_output=True)  # noqa: E731
        run("git", "init", "-q", "-b", "main")
        run(
            "git",
            "-c",
            "user.email=l@x",
            "-c",
            "user.name=l",
            "commit",
            "-q",
            "--allow-empty",
            "-m",
            "x",
        )
        run("git", "branch", "sprint-one")
        (tmp / ".xp" / "config.yml").write_text("release: sprint\ntrunk: main\n")
        os.chdir(tmp)

        first = tmp / "clone-one"
        first.mkdir()
        (first / "sprint_branch").write_text("sprint-one\n")
        os.environ["XP_DATA"] = str(first)
        if (got := close.integration_target()) != "sprint-one":
            return red(f"clone one's recorded sprint branch was ignored: {got!r}")

        second = tmp / "clone-two"
        second.mkdir()
        os.environ["XP_DATA"] = str(second)
        if (got := close.integration_target()) != "main":
            return red(f"clone two records nothing, yet the target is not trunk: {got!r}")
        # EMPTY is not ABSENT: the fallback two lines up is the one this file
        # exists to protect, so a truncated record reading as unset merges the
        # sprint to trunk with nothing said.
        (second / "sprint_branch").write_text("\n")
        if "is empty" not in refused(close.integration_target):
            return red("an empty branch record fell back to trunk instead of refusing")
        (second / "sprint_branch").write_text("sprint-missing\n")
        if "sprint-missing" not in refused(close.integration_target):
            return red("a recorded branch naming no ref did not refuse — it may merge to trunk")

        cfg = "release: sprint\ntrunk: main\nsprint_branch: sprint-one\n"
        (tmp / ".xp" / "config.yml").write_text(cfg)
        if "remove sprint_branch" not in refused(close.integration_target):
            return red("a tracked sprint_branch: was read instead of refused")
    return 0


if __name__ == "__main__":
    sys.exit(main())
