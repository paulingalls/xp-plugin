"""Tracked source boundaries remain adversarially testable after scan removal."""

import shutil

import pytest
from plan_review_install import PLUGIN, installed_launch
from runtime_source_support import plan_motion, review_motion

PLAN_MOTION = [
    "clean",
    "binary",
    "arrangement",
    "dirty",
    "addition",
    "hidden",
    "skip",
    "index",
    "head",
    "submodule-clean",
    "submodule-gitlink",
    "submodule-dirty",
]


@pytest.mark.parametrize("kind", PLAN_MOTION)
def test_plan_review_rejects_tracked_motion(tmp_path, kind):
    plan_motion(tmp_path, installed_launch(tmp_path), kind)


@pytest.mark.parametrize("kind", PLAN_MOTION)
def test_read_only_review_rejects_tracked_motion(tmp_path, kind):
    review_motion(tmp_path, kind)


@pytest.mark.meta
@pytest.mark.parametrize("stage", ["plan", "planner", "review"])
@pytest.mark.parametrize("kind", ["dirty", "addition", "hidden", "skip", "submodule-dirty"])
def test_source_guard_faults(tmp_path, monkeypatch, stage, kind):
    control, mutant = tmp_path / "control", tmp_path / "mutant"
    control.mkdir()
    mutant.mkdir()
    if stage in ("plan", "planner"):
        role = "planner" if stage == "planner" else "plan-reviewer"
        plan_motion(control, installed_launch(control), kind, role=role)
        mutation, target = (
            (
                (
                    "    if tracked_state(root=tree, include_untracked=True) != head:",
                    "    if False:",
                ),
                "scripts/spawn/story_stages.py",
            )
            if stage == "planner"
            else (
                ("card_for(story_id), source", "card_for(story_id), {}"),
                "scripts/plan_review.py",
            )
        )
        launch = installed_launch(mutant, mutation, target)
        with pytest.raises(AssertionError):
            plan_motion(mutant, launch, kind, role=role)
    else:
        review_motion(control, kind)
        installed = tmp_path / "installed"
        shutil.copytree(PLUGIN, installed)
        path = installed / "scripts/close/review_sequence.py"
        old = "    if motion or error:"
        text = path.read_text()
        assert old in text
        path.write_text(text.replace(old, '    motion = ""\n' + old))
        monkeypatch.setenv("XP_FLOW_TEST_CLOSE", str(installed / "scripts/close.py"))
        with pytest.raises(AssertionError):
            review_motion(mutant, kind)


@pytest.mark.parametrize("mutant", [False, pytest.param(True, marks=pytest.mark.meta)])
@pytest.mark.parametrize(
    "command", ["--binary", "--index-info", "--stage", "read-tree", "HEAD", "write-tree"]
)
def test_git_measurement_failure_refuses_truthfully(tmp_path, mutant, command):
    from plan_confirmation_support import consumer

    mutation = ("    if result.returncode:", "    if False:") if mutant else None
    launch = installed_launch(tmp_path, mutation, "scripts/git_source.py")
    repo, env, seen = consumer(tmp_path, initial_status="clean", initial_question=None)
    (tmp_path / "executor-stop").unlink()
    real_git = shutil.which("git")
    wrapper = tmp_path / "bin/git"
    wrapper.write_text(
        "#!/usr/bin/env python3\nimport os, sys\n"
        f"if {command!r} in sys.argv and 'diff.autoRefreshIndex=false' in sys.argv:\n"
        "    print('constructed Git failure', file=sys.stderr)\n"
        "    sys.exit(73)\n"
        f"os.execv({real_git!r}, [{real_git!r}, *sys.argv[1:]])\n"
    )
    wrapper.chmod(0o755)
    result = launch(repo, env, "story-042")

    def guarantee():
        from completed_executor_support import roles

        assert result.returncode == 2, result.stderr
        assert "constructed Git failure" in result.stderr
        assert "teammate" not in (roles(seen) if seen.exists() else [])
        assert "Traceback" not in result.stderr

    if mutant:
        with pytest.raises(AssertionError):
            guarantee()
    else:
        guarantee()


@pytest.mark.parametrize("mutant", [False, pytest.param(True, marks=pytest.mark.meta)])
def test_tier_config_motion_is_read_only_input(tmp_path, mutant):
    from completed_executor_support import tier_consumer

    mutation = ("if not same_inputs(before, after) or moved:", "if False:") if mutant else None
    launch = installed_launch(tmp_path, mutation, "scripts/spawn/execution.py")
    repo, env, _ = tier_consumer(tmp_path, "printf '# tier motion\\n' >> .xp/config.yml")
    result = launch(repo, env, "story-042")

    def guarantee():
        assert result.returncode == 2, result.stderr
        assert "inputs moved" in result.stderr

    if mutant:
        with pytest.raises(AssertionError):
            guarantee()
    else:
        guarantee()


@pytest.mark.meta
@pytest.mark.parametrize("mutant", [False, True])
def test_history_guard_faults(tmp_path, monkeypatch, mutant):
    from pathlib import Path

    from story_review_helpers import checkpoint, flow_repo, invoke

    repo, env, git, key, seen, _ = flow_repo(tmp_path)
    retained = git("rev-parse", "HEAD").stdout.strip()
    (repo / "unrelated.py").write_text("UNRELATED = True\n")
    assert git("add", "unrelated.py").returncode == 0
    assert git("commit", "-qm", "unrelated lead commit").returncode == 0
    dropped = git("rev-parse", "HEAD").stdout.strip()
    assert invoke(repo, env, key).returncode == 0
    sequence = checkpoint(env, key)
    report = Path(sequence["stages"]["solution"]["path"])
    saved, launches = report.read_bytes(), seen.read_bytes()
    assert git("reset", "--hard", retained).returncode == 0
    trunk = git("rev-parse", "main").stdout
    if mutant:
        installed = tmp_path / "installed"
        shutil.copytree(PLUGIN, installed)
        path = installed / "scripts/close/overlap.py"
        old = 'if git("merge-base", "--is-ancestor", shown, "HEAD", check=False).returncode:'
        text = path.read_text()
        assert old in text
        path.write_text(text.replace(old, "if False:"))
        monkeypatch.setenv("XP_FLOW_TEST_CLOSE", str(installed / "scripts/close.py"))
    result = invoke(repo, env, key, "land", "--merge-mode", "local")

    def guarantee():
        assert result.returncode == 2, result.stdout + result.stderr
        assert git("rev-parse", "main").stdout == trunk
        assert git("rev-parse", "HEAD").stdout.strip() == retained
        assert git("cat-file", "-e", dropped + "^{commit}").returncode == 0
        assert report.read_bytes() == saved and seen.read_bytes() == launches

    if mutant:
        with pytest.raises(AssertionError):
            guarantee()
    else:
        guarantee()


@pytest.mark.meta
@pytest.mark.parametrize("mutant", [False, True])
@pytest.mark.parametrize("damage", ["changed", "missing"])
def test_artifact_guard_faults(tmp_path, monkeypatch, mutant, damage):
    from pathlib import Path

    from story_review_helpers import checkpoint, flow_repo, invoke

    repo, env, git, key, seen, _ = flow_repo(tmp_path)
    assert invoke(repo, env, key).returncode == 0
    report = Path(checkpoint(env, key)["stages"]["solution"]["path"])
    if damage == "changed":
        report.write_text('{"blocking": ["unreviewed replacement"]}')
    else:
        report.unlink()
    saved = report.read_bytes() if report.exists() else None
    trunk, launches = git("rev-parse", "main").stdout, seen.read_bytes()
    if mutant:
        installed = tmp_path / "installed"
        shutil.copytree(PLUGIN, installed)
        path = installed / "scripts/close/review_sequence.py"
        old = "def check_reports(sequence):"
        text = path.read_text()
        assert old in text
        path.write_text(text.replace(old, old + "\n    return"))
        monkeypatch.setenv("XP_FLOW_TEST_CLOSE", str(installed / "scripts/close.py"))
    result = invoke(repo, env, key, "land", "--merge-mode", "local")

    def guarantee():
        assert result.returncode == 2, result.stdout + result.stderr
        assert git("rev-parse", "main").stdout == trunk
        assert (report.read_bytes() if report.exists() else None) == saved
        assert seen.read_bytes() == launches

    if mutant:
        with pytest.raises(AssertionError):
            guarantee()
    else:
        guarantee()


@pytest.mark.parametrize("tier_changed", [False, True])
def test_unrelated_config_motion_invalidates_executor(tmp_path, tier_changed):
    from completed_executor_support import completed, roles
    from plan_confirmation_support import events

    launch = installed_launch(tmp_path)
    repo, env, seen = completed(tmp_path, launch)
    config = tmp_path / "data/worktrees/story-042/.xp/config.yml"
    text = config.read_text()
    if tier_changed:
        text = text.replace("story: true", "story: true && true")
    config.write_text(text + "codex_sandbox: workspace-write\n")
    count = len(events(seen))
    preview = launch(repo, env, "resume", "story-042", "--dry-run")
    assert preview.returncode == 0, preview.stderr
    assert "Next stage: executor." in preview.stdout
    result = launch(repo, env, "resume", "story-042")
    assert result.returncode == 0, result.stderr
    assert roles(seen)[count:] == ["teammate", "reviewer"]


@pytest.mark.meta
def test_combined_config_motion_guard_fault(tmp_path, monkeypatch):
    control, mutant = tmp_path / "control", tmp_path / "mutant"
    control.mkdir()
    mutant.mkdir()
    test_unrelated_config_motion_invalidates_executor(control, True)
    install = installed_launch
    monkeypatch.setitem(
        globals(),
        "installed_launch",
        lambda root: install(
            root, ('return "".join(retained)', 'return ""'), "scripts/spawn/completion.py"
        ),
    )
    with pytest.raises(AssertionError):
        test_unrelated_config_motion_invalidates_executor(mutant, True)


@pytest.mark.parametrize("mutant", [False, pytest.param(True, marks=pytest.mark.meta)])
def test_source_measurement_preserves_user_index(tmp_path, mutant):
    import json

    from plan_confirmation_support import consumer

    mutation = ('            "--no-optional-locks",\n', "") if mutant else None
    launch = installed_launch(tmp_path, mutation, "scripts/git_source.py")
    repo, env, _seen = consumer(tmp_path, initial_status="clean", initial_question=None)
    (tmp_path / "executor-stop").unlink()
    observed = tmp_path / "index-measurement.json"
    stages = tmp_path / "cache/xp-plugin/fixture/scripts/spawn/story_stages.py"
    before = "    head = tracked_state(root=tree, include_untracked=True)"
    instrumented = (
        "    import os, json\n    from git_source import git\n"
        "    tracked = tree / '.xp/system.md'\n    measured = tracked.stat()\n"
        "    os.utime(tracked, ns=(measured.st_atime_ns, measured.st_mtime_ns + 5_000_000_000))\n"
        "    index = tree / git('rev-parse', '--git-path', 'index', root=tree).decode().strip()\n"
        "    saved = index.read_bytes()\n" + before + "\n"
        f"    Path({str(observed)!r}).write_text(\n"
        "        json.dumps([saved.hex(), index.read_bytes().hex()]))"
    )
    assert before in stages.read_text()
    stages.write_text(stages.read_text().replace(before, instrumented))
    result = launch(repo, env, "story-042")
    assert result.returncode == 0, result.stderr
    saved, after = json.loads(observed.read_text())
    if mutant:
        with pytest.raises(AssertionError):
            assert saved == after
    else:
        assert saved == after


def test_read_only_planner_rejects_second_dirty_edit(tmp_path):
    plan_motion(tmp_path, installed_launch(tmp_path), "dirty", role="planner")
