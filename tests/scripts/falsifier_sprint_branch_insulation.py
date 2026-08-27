"""Falsify per-clone sprint routing, fallback, and refusal boundaries."""

import contextlib
import io
import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[2] / "plugins" / "xp-plugin" / "scripts"))


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
        if close.integration_target() != "sprint-one":
            return 1

        second = tmp / "clone-two"
        second.mkdir()
        os.environ["XP_DATA"] = str(second)
        if close.integration_target() != "main":
            return 1
        (second / "sprint_branch").write_text("sprint-missing\n")
        if "sprint-missing" not in refused(close.integration_target):
            return 1

        (tmp / ".xp" / "config.yml").write_text("release: sprint\ntrunk: main\nsprint_branch:\n")
        if "remove sprint_branch" not in refused(close.integration_target):
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
