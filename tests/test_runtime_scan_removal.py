"""Consumer lifecycles leave ignored runtime relevance to agent judgment."""

import subprocess
import sys
from pathlib import Path

import pytest
from completed_executor_support import completed, git, roles
from plan_confirmation_support import consumer, events
from plan_review_install import installed_launch
from spawn_helpers import set_system_md
from story_review_helpers import checkpoint, flow_repo, invoke


def runtime(tree):
    subprocess.run(
        ["git", "config", "core.excludesfile", str(tree / ".runtime-ignore")], cwd=tree, check=True
    )
    (tree / ".runtime-ignore").write_text(".runtime-ignore\nnode_modules/\ndist/\n.pytest_cache/\n")
    for name in ("node_modules", "dist", ".pytest_cache"):
        (tree / name).mkdir(exist_ok=True)
        (tree / name / "runtime.bin").write_bytes(b"before")


@pytest.mark.parametrize("harness", ["claude", "codex"])
def test_runtime_motion_preserves_completed_stages(tmp_path, harness):
    launch = installed_launch(tmp_path)
    repo, env, seen = completed(tmp_path, launch, harness)
    tree = tmp_path / "data/worktrees/story-042"
    runtime(tree)
    head, count = git(tmp_path, "rev-parse", "HEAD"), len(events(seen))
    assert launch(repo, env, "resume", "story-042").returncode == 0
    for name in ("node_modules", "dist", ".pytest_cache"):
        (tree / name / "runtime.bin").write_bytes(b"after")
        (tree / name / "new.bin").write_bytes(b"created")
    preview = launch(repo, env, "resume", "story-042", "--dry-run")
    assert preview.returncode == 0, preview.stderr
    result = launch(repo, env, "resume", "story-042")
    assert result.returncode == 0, result.stderr
    assert roles(seen)[count:] == []
    assert git(tmp_path, "rev-parse", "HEAD") == head
    assert (tree / "node_modules/runtime.bin").read_bytes() == b"after"


@pytest.mark.parametrize("harness", ["claude", "codex"])
def test_clean_review_can_update_pytest_cache(tmp_path, harness):
    repo, env, git_cmd, key, seen, hooks = flow_repo(tmp_path, harness)
    runtime(repo)
    suite = tmp_path / "test_cache.py"
    suite.write_text("def test_cache():\n    assert True\n")
    cache = repo / ".pytest_cache/v/cache/nodeids"
    cache.parent.mkdir(parents=True)
    cache.write_text("[]")
    binary = tmp_path / "bin" / harness
    old = "report={'blocking':[]}"
    command = [
        sys.executable,
        "-m",
        "pytest",
        "-q",
        "-o",
        "cache_dir=" + str(repo / ".pytest_cache"),
        str(suite),
    ]
    addition = f"subprocess.run({command!r}, check=True, stdout=subprocess.DEVNULL)"
    binary.write_text(binary.read_text().replace(old, old + "\n" + addition))
    result = invoke(repo, env, key)
    assert result.returncode == 0, result.stderr
    assert cache.read_text() != "[]"
    assert seen.read_text().splitlines() == ["solution"]
    assert not hooks.exists()
    assert checkpoint(env, key)["status"] == "completed"
    assert not git_cmd("status", "--porcelain").stdout


def test_land_ignores_runtime_motion(tmp_path):
    repo, env, git_cmd, key, seen, _ = flow_repo(tmp_path)
    runtime(repo)
    assert invoke(repo, env, key).returncode == 0
    history = checkpoint(env, key)
    report = Path(history["stages"]["solution"]["path"])
    saved, launches = report.read_bytes(), seen.read_bytes()
    (repo / "node_modules/runtime.bin").write_bytes(b"after")
    result = invoke(repo, env, key, "land", "--merge-mode", "local")
    assert result.returncode == 0, result.stdout + result.stderr
    assert report.read_bytes() == saved and seen.read_bytes() == launches
    assert git_cmd("merge-base", "--is-ancestor", history["output"]["head"], "main").returncode == 0


def test_planning_ignores_unreadable_runtime(tmp_path):
    launch = installed_launch(tmp_path)
    repo, env, seen = consumer(tmp_path, initial_status="clean", initial_question=None)
    set_system_md(
        repo,
        "- Worktree bootstrap: `mkdir -p node_modules && "
        "printf secret > node_modules/runtime.bin && printf 'node_modules/\\n' "
        ">> $(git rev-parse --git-path info/exclude)`",
    )
    subprocess.run(["git", "branch", "-f", "main", "HEAD"], cwd=repo, env=env, check=True)
    trap = tmp_path / "trap"
    trap.mkdir()
    (trap / "sitecustomize.py").write_text(
        "from pathlib import Path\noriginal = Path.lstat\n"
        "def deny(self, *a, **k):\n"
        "    if 'node_modules' in self.parts: raise PermissionError('runtime access trap')\n"
        "    return original(self, *a, **k)\nPath.lstat = deny\n"
    )
    env = env | {"PYTHONPATH": str(trap)}
    control = subprocess.run(
        [
            sys.executable,
            "-c",
            "from pathlib import Path; Path('node_modules/runtime.bin').lstat()",
        ],
        env=env,
        capture_output=True,
    )
    assert control.returncode != 0 and b"runtime access trap" in control.stderr
    (tmp_path / "executor-stop").unlink()
    result = launch(repo, env, "story-042")
    assert result.returncode == 0, result.stderr
    assert roles(seen) == ["planner", "plan-reviewer", "teammate", "reviewer"]


@pytest.mark.meta
@pytest.mark.parametrize("stage", ["planning", "resume", "review", "land"])
def test_runtime_guard_faults(tmp_path, monkeypatch, stage):
    import shutil

    from plan_review_install import PLUGIN

    cases = {
        "planning": lambda root: test_planning_ignores_unreadable_runtime(root),
        "resume": lambda root: test_runtime_motion_preserves_completed_stages(root, "claude"),
        "review": lambda root: test_clean_review_can_update_pytest_cache(root, "claude"),
        "land": test_land_ignores_runtime_motion,
    }
    control, mutant = tmp_path / "control", tmp_path / "mutant"
    control.mkdir()
    mutant.mkdir()
    cases[stage](control)
    installed = tmp_path / "installed"
    shutil.copytree(PLUGIN, installed)
    if stage == "land":
        path = installed / "scripts/close/review_sequence.py"
        old = "    sequence = load(story_id)"
        new = (
            "    if Path('node_modules/runtime.bin').read_bytes() == b'after':\n"
            "        return 'refused: faulty runtime policy'\n" + old
        )
    else:
        path = installed / "scripts/git_source.py"
        old = "    return {"
        name = ".pytest_cache/v/cache/nodeids" if stage == "review" else "node_modules/runtime.bin"
        new = (
            f"    runtime = root / {name!r}\n    if runtime.exists():\n"
            "        runtime.lstat()\n"
            "        modules['faulty_runtime'] = runtime.read_bytes().hex()\n" + old
        )
    text = path.read_text()
    assert old in text
    path.write_text(text.replace(old, new))
    if stage in ("planning", "resume"):

        def faulty_launch(root):
            def launch(repo, env, *args):
                return subprocess.run(
                    [sys.executable, str(installed / "scripts/spawn.py"), *args],
                    cwd=repo,
                    env=env | {"XP_SPAWN_TEST": "1"},
                    capture_output=True,
                    text=True,
                )

            return launch

        monkeypatch.setitem(globals(), "installed_launch", faulty_launch)
    else:
        monkeypatch.setenv("XP_FLOW_TEST_CLOSE", str(installed / "scripts/close.py"))
    with pytest.raises(AssertionError):
        cases[stage](mutant)


def test_ignored_submodule_runtime_preserves_completed_stages(tmp_path):
    from plan_confirmation_support import submodule_consumer

    repo, env, seen = submodule_consumer(tmp_path, "claude")
    binary = tmp_path / "bin/claude"
    binary.write_text(
        binary.read_text().replace(
            "human_question': 'Which lease value does the human authorize?'",
            "human_question': None",
        )
    )
    excludes = tmp_path / "dependency-excludes"
    excludes.write_text("runtime.cfg\n")
    set_system_md(
        repo,
        "- Worktree bootstrap: `git -c protocol.file.allow=always submodule update --init "
        f"&& git -C vendor config core.excludesfile {excludes} "
        "&& printf baseline > vendor/runtime.cfg`",
    )
    subprocess.run(["git", "branch", "-f", "main", "HEAD"], cwd=repo, env=env, check=True)
    launch = installed_launch(tmp_path)
    result = launch(repo, env, "story-042")
    assert result.returncode == 0, result.stderr
    tree = tmp_path / "data/worktrees/story-042"
    count, head = len(events(seen)), git(tmp_path, "rev-parse", "HEAD")
    (tree / "vendor/runtime.cfg").write_text("changed ignored dependency")
    preview = launch(repo, env, "resume", "story-042", "--dry-run")
    result = launch(repo, env, "resume", "story-042")
    assert preview.returncode == result.returncode == 0, result.stderr
    assert roles(seen)[count:] == []
    assert git(tmp_path, "rev-parse", "HEAD") == head
