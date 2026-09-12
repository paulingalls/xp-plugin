"""Falsify story land accepting changed paths its card's Files line never declared."""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPTS = Path(__file__).parents[2] / "plugins" / "xp-plugin" / "scripts"
CARD = (
    "# plan\n## Milestone 1\n### Sprint 1\n#### story-042 — scope   [planned]\n"
    "Context: demo.\nFiles: src/thing.py\nAC:\n- Given X, Then Z\nVerify: true\n"
)
RECEIPT = (
    "import sys\nsys.path.insert(0, sys.argv[1]); sys.path.insert(0, sys.argv[1] + '/spawn')\n"
    "from close import story_card\nfrom work import plan_path\nimport ready\n"
    "card, _status = story_card(plan_path().read_text(), 'story-042')\n"
    "sys.exit(ready.write_refresh_receipt('story-042', card, False) or 0)\n"
)


def red(why: str) -> int:
    print(why, file=sys.stderr)
    return 1


def land_preview(tmp: Path, undeclared: bool) -> subprocess.CompletedProcess:
    root = tmp / ("undeclared" if undeclared else "declared")
    repo, data, bin_dir = root / "repo", root / "data", root / "bin"
    for folder in (repo / ".xp", repo / "src", data / "markers", bin_dir):
        folder.mkdir(parents=True)
    (bin_dir / "claude").write_text(
        '#!/bin/sh\necho \'[{"id":"xp-plugin@xp-plugin","version":"v","scope":"user"}]\'\n'
    )
    (bin_dir / "claude").chmod(0o755)
    env = os.environ.copy()
    env.pop("XP_ROLE", None)
    env |= {
        "XP_DATA": str(data),
        "HOME": str(root),
        "PATH": f"{bin_dir}:/usr/bin:/bin",
        "GIT_AUTHOR_NAME": "l",
        "GIT_AUTHOR_EMAIL": "l@x",
        "GIT_COMMITTER_NAME": "l",
        "GIT_COMMITTER_EMAIL": "l@x",
    }

    def run(*argv: str) -> subprocess.CompletedProcess:
        return subprocess.run(argv, cwd=repo, env=env, capture_output=True, text=True)

    run("git", "init", "-q", "-b", "main")
    (repo / ".xp" / "config.yml").write_text(
        "trunk: main\nroles:\n  reviewer: claude/opus\ntests:\n  story: true\n"
    )
    (repo / ".xp" / "constraints.md").write_text("# Constraints\n1. C\n")
    (repo / ".xp" / "system.md").write_text("# System\nS\n")
    (repo / "src" / "thing.py").write_text("A = 1\n")
    (repo / "helper.py").write_text("B = 1\n")
    run("git", "add", "-A")
    run("git", "commit", "-qm", "base")
    (data / "plan.md").write_text(CARD)
    run(sys.executable, "-c", RECEIPT, str(SCRIPTS), "story-042")
    minted = run(sys.executable, str(SCRIPTS / "spawn.py"), "ready", "story-042")
    if minted.returncode:
        raise SystemExit(red(f"fixture: ready refused: {minted.stderr.strip()}"))
    plan = data / "plan.md"
    plan.write_text(plan.read_text().replace("[ready]", "[in-progress]"))
    run("git", "checkout", "-qb", "story-042-branch")
    (repo / "src" / "thing.py").write_text("A = 2\n")
    if undeclared:
        (repo / "helper.py").write_text("B = 2\n")
    run("git", "commit", "-qam", "story work")
    head = run("git", "rev-parse", "HEAD").stdout.strip()
    (data / "markers" / "story-042.close.json").write_text(
        json.dumps(
            {
                "rounds": [{"fixed": [], "blocking": [], "noted": []}],
                "reviewed_head": head,
                "shown_sha": head,
                "review_base": run("git", "merge-base", "main", "HEAD").stdout.strip(),
                "branch": "story-042-branch",
            }
        )
    )
    return run(
        sys.executable,
        str(SCRIPTS / "close.py"),
        "story",
        "story-042",
        "land",
        "--merge-mode",
        "local",
        "--dry-run",
    )


def main() -> int:
    with tempfile.TemporaryDirectory() as folder:
        tmp = Path(folder)
        declared = land_preview(tmp, undeclared=False)
        if declared.returncode:
            return red(f"a story changing only declared files cannot land: {declared.stderr}")
        undeclared = land_preview(tmp, undeclared=True)
        if not undeclared.returncode or "helper.py" not in undeclared.stderr:
            return red(
                "land accepted a story that changed helper.py, which its card's Files line"
                f" never declared (rc={undeclared.returncode})"
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
