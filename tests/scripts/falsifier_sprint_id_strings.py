"""Falsify a non-numeric sprint id through open, post-merge and the released NEXT."""

import os
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPTS = Path(__file__).parents[2] / "plugins" / "xp-plugin" / "scripts"
sys.path.insert(0, str(SCRIPTS))

PLAN = "# plan\n### Sprint 2b-11 — lettered\n#### story-201 — work   [{status}]\nVerify: true\n"


def red(why: str) -> int:
    print(why, file=sys.stderr)
    return 1


def main() -> int:
    import session_start

    with tempfile.TemporaryDirectory() as folder:
        tmp = Path(folder)
        data = tmp / "data"
        data.mkdir()
        (data / "plan.md").write_text(PLAN.format(status="ready"))
        (data / "sprint_branch").write_text("sprint-2b-11\n")
        os.environ["XP_DATA"] = str(data)
        if (got := session_start.next_action()) != (
            "NEXT: story-201 is [ready] — run `spawn.py story-201`"
        ):
            return red(f"an open lettered sprint does not name its card: {got!r}")
        if "story-201" not in (got := session_start.sprint_slice()):
            return red(f"an open lettered sprint's slice lacks its card: {got!r}")

        repo = tmp / "repo"
        repo.mkdir()
        who = {"GIT_AUTHOR_NAME": "l", "GIT_AUTHOR_EMAIL": "l@x"}
        env = os.environ | who | {"GIT_COMMITTER_NAME": "l", "GIT_COMMITTER_EMAIL": "l@x"}
        env.pop("XP_ROLE", None)
        g = lambda *a: subprocess.run(["git", *a], cwd=repo, env=env, capture_output=True)  # noqa: E731
        g("init", "-q", "-b", "main")
        (repo / ".xp").mkdir()
        (repo / ".xp" / "config.yml").write_text(
            "release: sprint\ntrunk: main\nversion_files: manifest.json\nlifecycle_command: true\n"
        )
        (repo / "manifest.json").write_text('{"version": "0.3.0"}\n')
        g("add", "-A")
        g("commit", "-qm", "base")
        g("tag", "v0.2.0")
        g("checkout", "-qb", "sprint-2b-11")
        g("commit", "-q", "--allow-empty", "-m", "sprint work")
        g("checkout", "-q", "main")
        g("merge", "-q", "--no-ff", "sprint-2b-11", "-m", "release Sprint 2b-11")
        (data / "plan.md").write_text(PLAN.format(status="done"))
        merged = subprocess.run(
            [sys.executable, str(SCRIPTS / "close.py"), "sprint", "2b-11", "post-merge"],
            cwd=repo,
            env=env,
            capture_output=True,
            text=True,
        )
        if merged.returncode:
            tagged = g("tag", "-l", "v0.3.0").stdout.strip()
            return red(
                f"post-merge of sprint 2b-11 failed (rc={merged.returncode}, tag left:"
                f" {bool(tagged)}): {merged.stderr.strip()[-400:]}"
            )
        if (data / "sprint_branch").exists():
            return red("post-merge of sprint 2b-11 succeeded but left the sprint branch recorded")
        if (got := session_start.next_action()) != (
            "NEXT: Sprint 2b-11 was released — run `/create-sprint`"
        ):
            return red(f"a released lettered sprint is not read as released: {got!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
