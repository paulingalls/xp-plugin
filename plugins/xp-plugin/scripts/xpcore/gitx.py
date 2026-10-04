"""Git, spoken through one helper so every failure carries the command that failed."""

import subprocess
from pathlib import Path


class GitError(Exception):
    pass


def _run(args: tuple[str, ...], cwd) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)


def git(*args: str, cwd=None, check: bool = True) -> str:
    """Stdout without surrounding newlines; leading spaces survive, porcelain status needs them."""
    proc = _run(args, cwd)
    if check and proc.returncode != 0:
        detail = (proc.stderr.strip() or proc.stdout.strip()).splitlines()
        raise GitError(f"git {' '.join(args)}: {detail[-1] if detail else f'rc {proc.returncode}'}")
    return proc.stdout.strip("\n")


def head(cwd=None) -> str:
    return git("rev-parse", "HEAD", cwd=cwd)


def current_branch(cwd=None) -> str:
    """Empty when HEAD is detached."""
    return git("branch", "--show-current", cwd=cwd)


def is_dirty(cwd=None, *, untracked: bool = True) -> bool:
    mode = "--untracked-files=normal" if untracked else "--untracked-files=no"
    return bool(git("status", "--porcelain", mode, cwd=cwd))


def branch_exists(name: str, cwd=None) -> bool:
    return _run(("show-ref", "--verify", "--quiet", f"refs/heads/{name}"), cwd).returncode == 0


def ref_exists(ref: str, cwd=None) -> bool:
    return _run(("rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"), cwd).returncode == 0


def fork_point(branch: str, base: str, cwd=None) -> str:
    return git("merge-base", base, branch, cwd=cwd)


def trial_merge(cwd, ref: str) -> str:
    """ "" when `ref` merges cleanly, else the conflict text. The caller aborts in a finally."""
    proc = _run(("merge", "--no-commit", "--no-ff", ref), cwd)
    if proc.returncode == 0:
        return ""
    conflicted = git("diff", "--name-only", "--diff-filter=U", cwd=cwd, check=False)
    text = (proc.stdout + proc.stderr).strip()
    return text + (f"\nconflicted files:\n{conflicted}" if conflicted else "")


def abort_merge(cwd) -> None:
    if _run(("rev-parse", "--verify", "--quiet", "MERGE_HEAD"), cwd).returncode == 0:
        git("merge", "--abort", cwd=cwd)


def worktree_add(path, branch: str, start: str, cwd=None) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    if branch_exists(branch, cwd):
        git("worktree", "add", str(path), branch, cwd=cwd)
    else:
        git("worktree", "add", "-b", branch, str(path), start, cwd=cwd)


def worktree_remove(path, cwd=None) -> None:
    # --force because ignored build output blocks a plain remove; callers refuse dirt first.
    git("worktree", "remove", "--force", str(path), cwd=cwd)


def common_dir(cwd=None) -> Path:
    return Path(git("rev-parse", "--path-format=absolute", "--git-common-dir", cwd=cwd))


def changed_files(base: str, head: str, cwd=None) -> list[str]:
    return git("diff", "--name-only", f"{base}..{head}", cwd=cwd).splitlines()


def diff_range(base: str, head: str, cwd=None) -> str:
    return git("diff", f"{base}..{head}", cwd=cwd)


def log_range(base: str, head: str, cwd=None) -> str:
    return git("log", "--format=%h %s", f"{base}..{head}", cwd=cwd)
