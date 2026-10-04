"""Direct Git facts and transient read-only action boundaries."""

import os
import subprocess
import tempfile
from pathlib import Path


def git(*args, root=None, environment=None, input=None):
    result = subprocess.run(
        [
            "git",
            "--no-optional-locks",
            "-c",
            "diff.autoRefreshIndex=false",
            "-c",
            "core.fsmonitor=false",
            "-c",
            "core.sparseCheckout=false",
            "-c",
            "core.splitIndex=false",
            "-c",
            "core.ignorestat=false",
            *args,
        ],
        cwd=root,
        env=environment,
        input=input,
        capture_output=True,
    )
    if result.returncode:
        raise OSError(result.stderr.decode(errors="replace").strip())
    return result.stdout


def pathspec(excluded):
    return [".", *(f":(exclude,literal){name}" for name in excluded)]


def tracked_state(excluded=(), *, root=None, include_untracked=False):
    root = Path(root or Path.cwd()).resolve()
    paths = pathspec(excluded)
    index = git("ls-files", "--stage", "-z", "--", *paths, root=root)
    diff = [
        "--binary",
        "--no-ext-diff",
        "--no-textconv",
        "--ignore-submodules=untracked",
        "--submodule=diff",
    ]
    # A fresh index exposes top-level hiding flags while retaining staged additions.
    with tempfile.TemporaryDirectory(prefix="xp-source-") as directory:
        environment = os.environ | {"GIT_INDEX_FILE": str(Path(directory) / "index")}
        git("read-tree", "--empty", root=root, environment=environment)
        git("update-index", "-z", "--index-info", root=root, environment=environment, input=index)
        worktree = git("diff", *diff, "--", *paths, root=root, environment=environment)
    return {
        "head": git("rev-parse", "HEAD", root=root).decode().strip(),
        "status": git(
            "status",
            "--porcelain",
            "--untracked-files=normal" if include_untracked else "--untracked-files=no",
            "--ignore-submodules=untracked",
            "--",
            *paths,
            root=root,
        ),
        "staged": git("diff", "--cached", *diff, "--", *paths, root=root),
        "worktree": worktree,
    }


def uncommitted(excluded=(), *, root=None):
    with tempfile.TemporaryDirectory(prefix="xp-execution-") as directory:
        environment = os.environ | {"GIT_INDEX_FILE": str(Path(directory) / "index")}
        git("read-tree", "HEAD", root=root, environment=environment)
        return git(
            "diff",
            "--binary",
            "--submodule=diff",
            "--no-ext-diff",
            "--no-textconv",
            "--ignore-submodules=untracked",
            "HEAD",
            "--",
            *pathspec(excluded),
            root=root,
            environment=environment,
        )


def staged_tree():
    index = git("ls-files", "--stage", "-z")
    with tempfile.TemporaryDirectory(prefix="xp-source-") as directory:
        temporary_objects = Path(directory) / "objects"
        temporary_objects.mkdir()
        environment = os.environ | {
            "GIT_INDEX_FILE": str(Path(directory) / "index"),
            "GIT_OBJECT_DIRECTORY": str(temporary_objects),
            "GIT_ALTERNATE_OBJECT_DIRECTORIES": "",
        }
        git("read-tree", "--empty", environment=environment)
        git("update-index", "-z", "--index-info", environment=environment, input=index)
        return git("write-tree", "--missing-ok", environment=environment).decode().strip()


def facts(excluded=()):
    return {
        "head": git("rev-parse", "HEAD").decode().strip(),
        "tree": staged_tree(),
        "clean": not git(
            "status",
            "--porcelain",
            "--untracked-files=no",
            "--ignore-submodules=untracked",
            "--",
            *pathspec(excluded),
        )
        and not uncommitted(excluded),
    }
