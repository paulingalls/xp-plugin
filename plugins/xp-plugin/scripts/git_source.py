"""Direct Git evidence for tracked source and history boundaries."""

import os
import subprocess
import tempfile
from pathlib import Path


def git(*args, root=None, environment=None):
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
        capture_output=True,
    )
    if result.returncode:
        raise OSError(result.stderr.decode(errors="replace").strip())
    return result.stdout


def tracked_state(excluded=(), *, root=None):
    root = Path(root or Path.cwd()).resolve()
    paths = [".", *(f":(exclude,literal){name}" for name in excluded)]
    index = git("ls-files", "--stage", "-z", "--", *paths, root=root)
    diff = ["--binary", "--no-ext-diff", "--no-textconv", "--ignore-submodules=untracked"]
    # A fresh index retains actual staged additions without the user's hiding flags.
    with tempfile.TemporaryDirectory(prefix="xp-source-") as directory:
        environment = os.environ | {"GIT_INDEX_FILE": str(Path(directory) / "index")}
        git("read-tree", "--empty", root=root, environment=environment)
        result = subprocess.run(
            ["git", "-c", "core.splitIndex=false", "update-index", "-z", "--index-info"],
            cwd=root,
            env=environment,
            input=index,
            capture_output=True,
        )
        if result.returncode:
            raise OSError(result.stderr.decode(errors="replace").strip())
        worktree = git("diff", *diff, "--", *paths, root=root, environment=environment)
    modules = {}
    for entry in index.split(b"\0"):
        if not entry.startswith(b"160000 "):
            continue
        name = os.fsdecode(entry.split(b"\t", 1)[1])
        directory = root / name
        if (directory / ".git").exists():
            modules[name] = tracked_state(root=directory)
    return {
        "status": git(
            "status", "--porcelain", "--ignore-submodules=untracked", "--", *paths, root=root
        ).hex(),
        "head": git("rev-parse", "HEAD", root=root).hex(),
        "index": index.hex(),
        "staged": git("diff", "--cached", *diff, "--", *paths, root=root).hex(),
        "worktree": worktree.hex(),
        "submodules": modules,
    }
