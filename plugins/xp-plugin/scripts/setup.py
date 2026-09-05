#!/usr/bin/env python3
"""Scaffold a repo for the xp process: .xp/ artifacts + the git-hook wall.

The roadmap is NOT among them — it is per clone, so it scaffolds into the
state root and three clones of one repo get three plans.

Never overwrites, hooks included: pre-existing routing (core.hooksPath,
.githooks/, any lefthook config) is left alone — rewiring someone's hooks is an
overwrite of behavior.
"""

import argparse
import shutil
import stat
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from env import env_path, plugin_version, write_env
from work import chdir_repo_root, plan_path

PLUGIN_ROOT = Path(__file__).parent.parent
TEMPLATES = PLUGIN_ROOT / "templates"
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


def scaffold_wall() -> tuple[str, bool]:
    """(summary, wrote_a_hook). The flag exists because the closing advice named a
    pre-commit hook unconditionally, including where we deliberately wrote none."""
    if routing := existing_hook_routing():
        return (
            f"existing hook routing found ({routing}) — left untouched. Point"
            " .xp/config.yml's tiers at that wall's OWN commands, so the two cannot"
            ' drift into different definitions of "fast". constraints_chars_cap is'
            " declared but no reachable constraints_size enforcer was installed; add"
            " an equivalent constraints_size command to the existing wall",
            False,
        )
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
            return "wall: lefthook.yml written; install FAILED (see stderr)", True
        return "wall: lefthook.yml written and installed", True
    write_hook_lib()
    for hook in ("pre-commit", "pre-merge-commit", "pre-push"):
        dst = Path(".githooks") / hook
        shutil.copy(TEMPLATES / f"githooks-{hook}", dst)
        dst.chmod(dst.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    subprocess.run(["git", "config", "core.hooksPath", ".githooks"], check=True)
    return "wall: .githooks scaffolded (core.hooksPath set)", True


def main() -> int:
    argparse.ArgumentParser(description=__doc__).parse_args()  # --help must not scaffold
    if not chdir_repo_root():
        return fail("refused: not inside a git repository")
    if Path(".xp").exists():
        return fail("refused: .xp/ already exists — setup never overwrites")
    if plan_path().exists():
        return fail(f"refused: a plan already exists at {plan_path()} — setup never overwrites")
    version = plugin_version(PLUGIN_ROOT)
    if version == "unknown":
        return fail(
            f"refused: {PLUGIN_ROOT / '.claude-plugin' / 'plugin.json'} has no usable version"
        )
    try:
        write_env(PLUGIN_ROOT, version)
    except Exception as exc:
        return fail(f"refused: could not seed {env_path()}: {exc}")
    Path(".xp").mkdir()
    for name in ("config.yml", "constraints.md", "system.md"):
        shutil.copy(TEMPLATES / name, Path(".xp") / name)
    plan_path().parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(TEMPLATES / "plan.md", plan_path())
    wall, wrote_hook = scaffold_wall()
    third = "; (3) add your linter to the pre-commit hook." if wrote_hook else ""
    print(
        f".xp/ scaffolded (config, seeded constraints, system)\n"
        f"plan scaffolded at {plan_path()} — PER CLONE, outside the repo\n"
        f"env.json seeded at {env_path()} — where anything NOT spawned from the plugin"
        f" reads its root\n{wall}\n"
        "Edit next: (1) tests.fast/story/full in .xp/config.yml — the wall reads them"
        f" at run time; (2) .xp/system.md{third or '.'}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
