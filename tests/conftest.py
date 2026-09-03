"""Git exports GIT_DIR to hook subprocesses, and the tests shell out to git.

In a MAIN tree git exports the relative `.git`, which re-resolves against each
test's fixture repo and behaves correctly. In a WORKTREE it exports an ABSOLUTE
path, so any inherited git call runs against the real index with the fixture
directory as its work tree — every tracked file stages as deleted and the
fixture never gets its commit. That is not hypothetical: it is why the first
real teammate spawn failed (bug 7fed6ef1). spawn.py commits the [in-progress]
flip inside the worktree, that commit runs the pre-commit wall, the wall runs
this suite, and three tests that pass in the lead's tree red there.

Stripped here rather than at each call site so a test added later inherits the
isolation. ../xp-agents reached the same conclusion (v2.5.0) via `env -u` in its
hook runner plus a registry and a mirror test; the runner is not the only way to
invoke pytest, and this is one file.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

for _var in ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE"):
    os.environ.pop(_var, None)

# The scripts dir, seeded ONCE for every test file: after the sprint-004 split,
# `from spawn import …` worked only when a sibling file had already seeded the
# path — 14 tests red under `pytest tests/test_spawn_run.py` alone (story-019
# close review, noted[]), invisible because every Verify line ran a seeder too.
# The spawn package too, since story-073 ended spawn.py's argv re-export.
_SCRIPTS = Path(__file__).parent.parent / "plugins" / "xp-plugin" / "scripts"
sys.path.insert(0, str(_SCRIPTS))
sys.path.insert(0, str(_SCRIPTS / "spawn"))

_TEMPLATE_ENV = "XP_TEST_REPO_TEMPLATES"
_SLOW = Path(__file__).parent / "slow_tests.json"


def pytest_collection_modifyitems(items):
    """Mark by MEASURED duration, because hand-marking drifted. The 31 hand marks
    named tests someone found annoying — salvage, teardown, concurrency — while
    the suite's real cost is a PLATEAU: 969 tests, mean 1024ms, median 730ms,
    because nearly every test spawns subprocesses. The top 40 are 19% of the
    cost, so a slow-LIST could never have bought the gate back; only a threshold
    can. Hand marks stay: they are deliberate and cheap to keep."""
    slow = pytest.mark.slow
    ids = set(json.loads(_SLOW.read_text())["ids"])
    for item in items:
        if item.nodeid in ids:
            item.add_marker(slow)


def pytest_configure(config):
    if _TEMPLATE_ENV in os.environ:
        return
    holder = tempfile.TemporaryDirectory(prefix="xp-test-repo-templates-")
    root = Path(holder.name)
    env = {"PATH": "/usr/bin:/bin", "HOME": str(root)}
    identities = {
        "close": ("t@t", "t"),
        "session-start": ("t@t", "t"),
        "spawn": ("ada@example.com", "Ada L"),
        "sprint": ("t@t", "t"),
    }
    for name, (email, user) in identities.items():
        repo = root / name
        repo.mkdir()
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, env=env, check=True)
        subprocess.run(["git", "config", "user.email", email], cwd=repo, env=env, check=True)
        subprocess.run(["git", "config", "user.name", user], cwd=repo, env=env, check=True)
    os.environ[_TEMPLATE_ENV] = str(root)
    from close_helpers import make_repo as make_close_repo
    from session_start_helpers import xp_repo
    from spawn_helpers import make_repo as make_spawn_repo
    from sprint_helpers import make_repo as make_sprint_repo

    for name, build in {
        "close-full": make_close_repo,
        "session-start-full": xp_repo,
        "spawn-full": make_spawn_repo,
        "sprint-full": make_sprint_repo,
    }.items():
        build_root = root / f"build-{name}"
        build_root.mkdir()
        repo, *_rest = build(build_root)
        shutil.copytree(repo, root / name)
    config._xp_repo_templates = holder


def pytest_unconfigure(config):
    if holder := getattr(config, "_xp_repo_templates", None):
        os.environ.pop(_TEMPLATE_ENV, None)
        holder.cleanup()
