"""Scaffold a project: .xp/ from the templates, the git-hook wall, and an empty plan."""

import shutil
import subprocess
from pathlib import Path

from xpcore.config import data_root, plugin_root, refuse, repo_root
from xpcore.gitx import git
from xpcore.session import recover_command

XP_FILES = ("config.yml", "system.md", "constraints.md")
GITHOOKS = ("pre-commit", "pre-merge-commit", "pre-push", "sprint")
LEFTHOOK_CONFIGS = ("lefthook.yml", ".lefthook.yml", "lefthook.yaml", "lefthook.toml")
LEFTHOOK_CONFIGS += ("lefthook.json",)
NEXT = (
    "next: fill .xp/config.yml roles and version_files, .xp/system.md, the hook test commands"
    " (every EDIT-ME); then /create-sprint"
)


def _templates() -> Path:
    return plugin_root() / "templates"


def existing_routing(root: Path) -> str:
    """What already routes this repo's hooks, or "". Rewiring someone's hooks is not ours."""
    if hooks_path := git("config", "--get", "core.hooksPath", cwd=root, check=False):
        return f"core.hooksPath={hooks_path}"
    for name in LEFTHOOK_CONFIGS:
        if (root / name).exists():
            return name
    if (root / ".githooks").exists():
        return ".githooks/"
    hooks = root / git("rev-parse", "--git-path", "hooks", cwd=root)
    live = sorted(p.name for p in hooks.glob("*") if not p.name.endswith(".sample"))
    return f"live hooks in .git/hooks ({', '.join(live)})" if live else ""


def _copy(template: str, dest: Path, executable: bool = False) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(_templates() / template, dest)
    if executable:
        dest.chmod(0o755)


def _wall(root: Path) -> int:
    if routing := existing_routing(root):
        print(
            f"wall skipped: {routing} already routes this repo's hooks, so nothing was written"
            " there. Add to it: a pre-commit tests command that runs under a minute, a pre-push"
            " tests command, and a hook named `sprint` (lefthook `sprint:` or .githooks/sprint)"
            " that runs the release suite; sprint land runs it."
        )
        return 0
    _copy("hook-lib.sh", root / ".githooks" / "hook-lib.sh")
    if shutil.which("lefthook"):
        _copy("lefthook.yml", root / "lefthook.yml")
        # lefthook runs pre-push scripts from source_dir; lefthook.yml names this one.
        _copy("lefthook-pre-push-secrets", root / ".githooks" / "pre-push" / "secrets", True)
        rc = subprocess.run(["lefthook", "install"], cwd=root).returncode
        if rc != 0:
            print(f"wall: lefthook.yml written but `lefthook install` exited {rc}; run it")
            return 1
        print("wall: lefthook.yml written and installed")
        return 0
    for hook in GITHOOKS:
        _copy(f"githooks-{hook}", root / ".githooks" / hook, True)
    git("config", "core.hooksPath", ".githooks", cwd=root)
    print("wall: .githooks/ written and core.hooksPath set (lefthook is not on PATH)")
    return 0


def cmd_setup(args) -> int:
    root = repo_root()
    xp = root / ".xp"
    if xp.exists():
        refuse(f"{xp} already exists; edit the files there")
    for name in XP_FILES:
        _copy(name, xp / name)
    print(f"wrote {', '.join(f'.xp/{n}' for n in XP_FILES)}")
    rc = _wall(root)
    plan = data_root() / "plan.md"
    if not plan.exists():
        _copy("plan.md", plan)
        print(f"wrote {plan}")
    print(f"recover: {recover_command()}")
    print(NEXT)
    return rc
