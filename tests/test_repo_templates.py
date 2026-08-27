import os
import subprocess
import time
from pathlib import Path

import pytest
from close_helpers import make_repo as make_close_repo
from session_start_helpers import xp_repo
from spawn_helpers import make_repo as make_spawn_repo
from sprint_helpers import CONFIG, PLAN, stub_reviewer
from sprint_helpers import make_repo as make_sprint_repo

TIMING_RUNS = 5
# The lead measured 13.5x over 25 iterations; 5x is the floor a revert to the git
# build (measured 1.0x) cannot clear and ambient load cannot fake.
MIN_SPEEDUP = 5.0


def make_close_skeleton(root):
    return make_close_repo(root, status="planned")


@pytest.mark.parametrize(
    ("template_name", "build", "tracked"),
    [
        ("close-full", make_close_repo, Path("src/thing.py")),
        ("close", make_close_skeleton, Path("src/thing.py")),
        ("spawn-full", make_spawn_repo, Path("drift.txt")),
        ("session-start-full", xp_repo, Path("f.py")),
        ("sprint-full", make_sprint_repo, Path("src.py")),
    ],
)
def test_a_mutated_repo_cannot_change_the_template_or_next_copy(
    tmp_path, template_name, build, tracked
):
    template = Path(os.environ["XP_TEST_REPO_TEMPLATES"]) / template_name
    template_config = (template / ".git" / "config").read_bytes()
    first_root = tmp_path / "first"
    first_root.mkdir()
    first, *_rest = build(first_root)
    original = (first / tracked).read_text()
    with (first / ".git" / "config").open("a") as config:
        config.write("[test]\n\tshared = mutated\n")
    (first / tracked).write_text("MUTATED = True\n")

    second_root = tmp_path / "second"
    second_root.mkdir()
    second, *rest = build(second_root)
    second_git = rest[-1]

    assert second_git("config", "--get", "test.shared").returncode != 0
    assert (second / tracked).read_text() == original
    assert (template / ".git" / "config").read_bytes() == template_config
    # by INODE, not by path: distinct paths are true by construction and assert
    # nothing, while a hand-out that hard-links or symlinks shares the inode and
    # every write above reaches the template through it.
    inodes = {(p / ".git" / "config").stat().st_ino for p in (first, second, template)}
    assert len(inodes) == 3


@pytest.mark.parametrize(
    ("template_name", "build"),
    [
        ("close-full", make_close_repo),
        ("spawn-full", make_spawn_repo),
        ("session-start-full", xp_repo),
        ("sprint-full", make_sprint_repo),
    ],
)
def test_a_default_call_is_served_by_the_finished_template(tmp_path, template_name, build):
    """Each helper decides copy-vs-build by comparing its arguments against a
    hand-written copy of its own defaults. Change a default without changing that
    comparison and every default call silently falls back to the git build: green
    suite, no warning, the whole story reverted. Identical HEAD proves the repo IS
    the copy, since a rebuild re-commits and gets its own sha."""
    template = Path(os.environ["XP_TEST_REPO_TEMPLATES"]) / template_name
    root = tmp_path / "built"
    root.mkdir()
    repo, *_rest = build(root)
    env = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path)}
    head = lambda where: subprocess.run(  # noqa: E731
        ["git", "rev-parse", "HEAD"], cwd=where, env=env, capture_output=True, text=True
    ).stdout.strip()
    assert head(repo) and head(repo) == head(template)


def branches(repo):
    """Explicit env, like every git call in this file: an inherited GIT_DIR runs
    against the real repository with the fixture as its work tree (bug 7fed6ef1)."""
    return subprocess.run(
        ["git", "branch", "--format=%(refname:short)"],
        cwd=repo,
        env={"PATH": "/usr/bin:/bin", "HOME": str(repo.parent)},
        capture_output=True,
        text=True,
    ).stdout.split()


@pytest.mark.parametrize(
    ("build", "served_what_was_asked_for"),
    [
        pytest.param(
            lambda root: make_close_repo(root, system=False),
            lambda repo, root: not (repo / ".xp" / "system.md").exists(),
            id="close-system",
        ),
        pytest.param(
            lambda root: make_close_repo(root, teardown="echo bye"),
            lambda repo, root: "echo bye" in (repo / ".xp" / "system.md").read_text(),
            id="close-teardown",
        ),
        pytest.param(
            lambda root: make_close_repo(root, bootstrap="echo hi"),
            lambda repo, root: "echo hi" in (repo / ".xp" / "system.md").read_text(),
            id="close-bootstrap",
        ),
        pytest.param(
            lambda root: make_close_repo(root, teardown_timeout=7),
            lambda repo, root: "teardown_timeout: 7" in (repo / ".xp" / "config.yml").read_text(),
            id="close-teardown-timeout",
        ),
        pytest.param(
            lambda root: make_close_repo(root, branch="dev"),
            lambda repo, root: "dev" in branches(repo) and "main" not in branches(repo),
            id="close-branch",
        ),
        pytest.param(
            # the credential, not the bracket: the template path always mints one,
            # so a lost `status` term hands every caller a cleared card
            lambda root: make_close_repo(root, status="planned"),
            lambda repo, root: "[planned]" in (root / "data" / "plan.md").read_text(),
            id="close-status",
        ),
        pytest.param(
            lambda root: make_spawn_repo(root, trunk="dev"),
            lambda repo, root: (root / "data" / "sprint_branch").read_text().strip() == "dev",
            id="spawn-trunk",
        ),
        pytest.param(
            lambda root: make_sprint_repo(root, config=CONFIG + "  fast: true\n"),
            lambda repo, root: "fast: true" in (repo / ".xp" / "config.yml").read_text(),
            id="sprint-config",
        ),
    ],
)
def test_a_non_default_call_is_never_served_the_finished_template(
    tmp_path, build, served_what_was_asked_for
):
    """The other direction, and the one that fails SILENTLY. Each helper decides
    copy-vs-build by hand-restating its own defaults, and only the default
    direction was guarded — so a caller asking for a non-default fixture could be
    served the finished one and never know. Measured on this tree: delete `and
    system` from close_helpers.py's predicate and make_repo(system=False) copies
    close-full, which HAS .xp/system.md, while the whole fast tier stays green,
    because test_a_missing_system_file_is_the_no_teardown_arm only asserts rc==0
    and a removed worktree. The arm it names goes unexecuted while looking covered.

    Asserted as "the option took effect", never as "HEAD differs from the
    template": over-specifying a predicate costs speed and the wrong assertion
    would forbid ever fixing that.

    THREE PREDICATE TERMS ARE DELIBERATELY UNARMED, because they are written to
    the data-root plan BEFORE the copy-vs-build fork and are therefore honored on
    both paths — close's `verify`, spawn's `executor` and sprint's `plan`. Dropping
    any of them leaves the fast tier green (measured, 830 passed) and costs nothing
    but a rebuild. Spawn's `status` is unarmed for the opposite reason: it is
    self-guarding, since the helper asserts its `spawn ready` mint exits 0 and a
    non-[planned] card refuses it. And session_start_helpers.xp_repo takes NO
    options at all, so it has no non-default call to make — the default-direction
    test above is its whole guard, and giving it one is what would need an arm here.
    """
    repo, *_rest = build(tmp_path)
    assert served_what_was_asked_for(repo, tmp_path), (
        "a non-default option was silently served the finished template"
    )


def test_hostile_worktree_git_variables_cannot_reach_a_decoy(monkeypatch, tmp_path):
    decoy = tmp_path / "decoy"
    decoy.mkdir()
    clean_env = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path)}
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=decoy, env=clean_env, check=True)
    (decoy / "sentinel").write_text("untouched\n")
    subprocess.run(["git", "add", "sentinel"], cwd=decoy, env=clean_env, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=decoy",
            "-c",
            "user.email=decoy@example.com",
            "commit",
            "-qm",
            "decoy base",
        ],
        cwd=decoy,
        env=clean_env,
        check=True,
    )
    decoy_head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=decoy,
        env=clean_env,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    for name, value in {
        "GIT_DIR": decoy / ".git",
        "GIT_WORK_TREE": decoy,
        "GIT_COMMON_DIR": decoy / ".git",
        "GIT_INDEX_FILE": decoy / ".git" / "index",
    }.items():
        monkeypatch.setenv(name, str(value))

    fixture_root = tmp_path / "fixture"
    fixture_root.mkdir()
    repo, env, git = make_close_repo(fixture_root)

    assert git("log", "-1", "--pretty=%s").stdout.strip() == "story work"
    assert (
        subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=decoy,
            env=clean_env,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        == decoy_head
    )
    assert (decoy / "sentinel").read_text() == "untouched\n"
    assert repo != decoy and env["HOME"] == str(fixture_root)


def build_sprint_repo_with_git(root):
    repo = root / "repo"
    (repo / ".xp").mkdir(parents=True)
    env = {
        "PATH": f"{stub_reviewer(root)}:/usr/bin:/bin",
        "HOME": str(root),
        "XP_DATA": str(root / "data"),
    }
    git = lambda *args: subprocess.run(  # noqa: E731
        ["git", *args], cwd=repo, env=env, capture_output=True, text=True, check=True
    )
    git("init", "-q", "-b", "main")
    git("config", "user.email", "t@t")
    git("config", "user.name", "t")
    state_plan = root / "data" / "plan.md"
    state_plan.parent.mkdir(parents=True)
    state_plan.write_text(PLAN)
    (repo / ".xp" / "config.yml").write_text(CONFIG)
    (repo / ".xp" / "constraints.md").write_text("# Constraints\n1. CONSTRAINT-SENTINEL\n")
    (repo / ".xp" / "system.md").write_text("# System\nSYSTEM-SENTINEL\n")
    (repo / "src.py").write_text("A = 1\n")
    git("add", "-A")
    git("commit", "-qm", "base")
    git("checkout", "-qb", "sprint-002")
    (repo / "src.py").write_text("A = 1\nB = 'SPRINT-ONLY-SENTINEL'\n")
    git("add", "-A")
    git("commit", "-qm", "story work on the sprint branch")
    return repo


def tracked_content(repo):
    env = {"PATH": "/usr/bin:/bin", "HOME": str(repo.parent)}
    return subprocess.run(
        ["git", "ls-tree", "-r", "HEAD"], cwd=repo, env=env, capture_output=True, text=True
    ).stdout


@pytest.mark.slow
def test_finished_fixture_copy_cost_against_git_build(tmp_path):
    copy_seconds = 0.0
    git_seconds = 0.0
    for index in range(TIMING_RUNS):
        copy_root = tmp_path / f"copy-{index}"
        copy_root.mkdir()
        started = time.perf_counter()
        copied, *_rest = make_sprint_repo(copy_root)
        copy_seconds += time.perf_counter() - started

        git_root = tmp_path / f"git-{index}"
        git_root.mkdir()
        started = time.perf_counter()
        built = build_sprint_repo_with_git(git_root)
        git_seconds += time.perf_counter() - started

    copy_ms = copy_seconds * 1000 / TIMING_RUNS
    git_ms = git_seconds * 1000 / TIMING_RUNS
    print(f"fixture cost {copy_ms:.2f}ms copy / {git_ms:.2f}ms git = {git_ms / copy_ms:.2f}x")
    # The git leg is a frozen copy of what make_repo used to do, so nothing but
    # this ties the two halves to the same repo: let them drift and the ratio
    # keeps printing while it has stopped comparing like with like.
    assert tracked_content(copied) == tracked_content(built)
    assert git_ms / copy_ms >= MIN_SPEEDUP, f"{git_ms / copy_ms:.2f}x is under {MIN_SPEEDUP}x"
