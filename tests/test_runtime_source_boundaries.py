"""Tracked source boundaries remain adversarially testable after scan removal."""

import shutil

import pytest
from plan_review_install import PLUGIN, installed_launch
from runtime_source_support import plan_motion, review_motion

PLAN_MOTION = [
    "clean",
    "dirty",
    "addition",
    "hidden",
    "skip",
    "index",
    "head",
    "submodule-clean",
    "submodule-gitlink",
    "submodule-dirty",
    "submodule-hidden",
]


@pytest.mark.parametrize("kind", PLAN_MOTION)
def test_plan_review_rejects_tracked_motion(tmp_path, kind):
    plan_motion(tmp_path, installed_launch(tmp_path), kind)


@pytest.mark.parametrize("kind", PLAN_MOTION)
def test_read_only_review_rejects_tracked_motion(tmp_path, kind):
    review_motion(tmp_path, kind)


@pytest.mark.meta
@pytest.mark.parametrize("stage", ["plan", "review"])
@pytest.mark.parametrize(
    "kind", ["dirty", "addition", "hidden", "skip", "submodule-dirty", "submodule-hidden"]
)
def test_source_guard_faults(tmp_path, monkeypatch, stage, kind):
    control, mutant = tmp_path / "control", tmp_path / "mutant"
    control.mkdir()
    mutant.mkdir()
    if stage == "plan":
        plan_motion(control, installed_launch(control), kind)
        launch = installed_launch(
            mutant,
            ("card_for(story_id), source", "card_for(story_id), {}"),
            "scripts/plan_review.py",
        )
        with pytest.raises(AssertionError):
            plan_motion(mutant, launch, kind)
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
@pytest.mark.parametrize("command", ["--binary", "--index-info"])
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
        f"if {command!r} in sys.argv:\n    print('constructed Git failure', file=sys.stderr)\n"
        "    sys.exit(73)\n"
        f"os.execv({real_git!r}, [{real_git!r}, *sys.argv[1:]])\n"
    )
    wrapper.chmod(0o755)
    result = launch(repo, env, "story-042")

    def guarantee():
        from completed_executor_support import roles

        assert result.returncode == 2, result.stderr
        assert "constructed Git failure" in result.stderr
        assert "teammate" not in roles(seen)
        assert "Traceback" not in result.stderr

    if mutant:
        with pytest.raises(AssertionError):
            guarantee()
    else:
        guarantee()


@pytest.mark.parametrize("mutant", [False, pytest.param(True, marks=pytest.mark.meta)])
def test_tier_config_motion_is_read_only_input(tmp_path, mutant):
    from completed_executor_support import tier_consumer

    mutation = ("return before == after", "return True") if mutant else None
    launch = installed_launch(tmp_path, mutation, "scripts/spawn/completion.py")
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


def test_unrelated_config_motion_invalidates_executor(tmp_path):
    from completed_executor_support import completed, roles
    from plan_confirmation_support import events

    launch = installed_launch(tmp_path)
    repo, env, seen = completed(tmp_path, launch)
    config = tmp_path / "data/worktrees/story-042/.xp/config.yml"
    config.write_text(config.read_text() + "codex_sandbox: workspace-write\n")
    count = len(events(seen))
    preview = launch(repo, env, "resume", "story-042", "--dry-run")
    assert preview.returncode == 0, preview.stderr
    assert "Next stage: executor." in preview.stdout
    result = launch(repo, env, "resume", "story-042")
    assert result.returncode == 0, result.stderr
    assert roles(seen)[count:] == ["teammate", "reviewer"]


@pytest.mark.parametrize("mutant", [False, pytest.param(True, marks=pytest.mark.meta)])
def test_source_measurement_preserves_user_index(tmp_path, mutant):
    import os
    import subprocess
    import sys

    from story_review_helpers import flow_repo

    repo, env, git, _key, _seen, _hooks = flow_repo(tmp_path)
    tracked = repo / "src/thing.py"
    measured = tracked.stat()
    os.utime(tracked, ns=(measured.st_atime_ns, measured.st_mtime_ns + 5_000_000_000))
    index = repo / git("rev-parse", "--git-path", "index").stdout.strip()
    saved = index.read_bytes()
    installed = tmp_path / "installed"
    shutil.copytree(PLUGIN, installed)
    if mutant:
        path = installed / "scripts/git_source.py"
        old = '            "--no-optional-locks",\n'
        text = path.read_text()
        assert old in text
        path.write_text(text.replace(old, ""))
    code = (
        f"import sys; sys.path.insert(0, {str(installed / 'scripts')!r}); "
        f"from git_source import tracked_state; tracked_state(root={str(repo)!r})"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=repo, env=env, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr

    def guarantee():
        assert index.read_bytes() == saved

    if mutant:
        with pytest.raises(AssertionError):
            guarantee()
    else:
        guarantee()
