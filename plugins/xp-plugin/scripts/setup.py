#!/usr/bin/env python3
"""Scaffold a repo for the xp process: .xp/ artifacts + the git-hook wall.

Never overwrites: an existing .xp/ refuses outright, and any pre-existing hook
routing (core.hooksPath, .githooks/, any lefthook config) is left untouched —
rewiring someone's hooks is an overwrite of behavior.
"""

import argparse
import shutil
import stat
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from work import chdir_repo_root

TEMPLATES = Path(__file__).parent.parent / "templates"
LEFTHOOK_CONFIGS = [
    "lefthook.yml",
    ".lefthook.yml",
    "lefthook.yaml",
    "lefthook.toml",
    "lefthook.json",
]


def fail(msg: str) -> int:
    print(msg, file=sys.stderr)
    return 2


def existing_hook_routing() -> str:
    hooks_path = subprocess.run(
        ["git", "config", "core.hooksPath"], capture_output=True, text=True
    ).stdout.strip()
    if hooks_path:
        return f"core.hooksPath={hooks_path}"
    git_hooks = subprocess.run(
        ["git", "rev-parse", "--git-path", "hooks"], capture_output=True, text=True
    ).stdout.strip()
    live = [p.name for p in Path(git_hooks).glob("*") if not p.name.endswith(".sample")]
    if live:
        return f"live hooks in .git/hooks ({', '.join(sorted(live)[:3])})"
    if Path(".githooks").exists():
        return ".githooks/"
    for name in LEFTHOOK_CONFIGS:
        if Path(name).exists():
            return name
    return ""


def write_hook_lib() -> None:
    Path(".githooks").mkdir()
    shutil.copy(TEMPLATES / "hook-lib.sh", ".githooks/hook-lib.sh")


def scaffold_wall() -> str:
    if routing := existing_hook_routing():
        return f"existing hook routing found ({routing}) — left untouched; wire the tiers yourself"
    if shutil.which("lefthook"):
        write_hook_lib()
        shutil.copy(TEMPLATES / "lefthook.yml", "lefthook.yml")
        installed = subprocess.run(["lefthook", "install"], check=False)
        if installed.returncode != 0:
            print(
                "wall: lefthook.yml written but `lefthook install` FAILED — run it"
                " yourself and read its error",
                file=sys.stderr,
            )
            return "wall: lefthook.yml written; install FAILED (see stderr)"
        return "wall: lefthook.yml written and installed"
    write_hook_lib()
    for hook in ("pre-commit", "pre-push"):
        dst = Path(".githooks") / hook
        shutil.copy(TEMPLATES / f"githooks-{hook}", dst)
        dst.chmod(dst.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    subprocess.run(["git", "config", "core.hooksPath", ".githooks"], check=True)
    return "wall: .githooks scaffolded (core.hooksPath set)"


def main() -> int:
    argparse.ArgumentParser(description=__doc__).parse_args()  # --help must not scaffold
    if not chdir_repo_root():
        return fail("refused: not inside a git repository")
    if Path(".xp").exists():
        return fail("refused: .xp/ already exists — setup never overwrites")
    Path(".xp").mkdir()
    for name in ("config.yml", "constraints.md", "system.md", "plan.md"):
        shutil.copy(TEMPLATES / name, Path(".xp") / name)
    wall = scaffold_wall()
    print(
        f".xp/ scaffolded (config, seeded constraints, system + plan skeletons)\n{wall}\n"
        "Edit next: (1) tests.fast/story/full in .xp/config.yml — the wall reads them"
        " at run time; (2) .xp/system.md; (3) add your linter to the pre-commit hook."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
