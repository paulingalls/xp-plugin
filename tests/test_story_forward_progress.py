"""Actual stage outcomes, rather than commit ownership, drive execution."""

import json

import pytest
from plan_confirmation_support import consumer, events
from plan_review_install import installed_launch


def test_inherited_complete_candidate_needs_no_successor_commit(tmp_path):
    launch = installed_launch(tmp_path)
    repo, env, seen = consumer(tmp_path, initial_status="clean", initial_question=None)
    first = launch(repo, env, "story-042")
    assert first.returncode != 0
    tree = tmp_path / "data/worktrees/story-042"
    import subprocess

    (tree / "src").mkdir(exist_ok=True)
    (tree / "src/thing.py").write_text("DONE = True\n")
    subprocess.run(["git", "add", "src"], cwd=tree, env=env, check=True)
    subprocess.run(
        ["git", "commit", "-qm", "inherited implementation"], cwd=tree, env=env, check=True
    )
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=tree, text=True)
    (tmp_path / "executor-stop").unlink()
    binary = tmp_path / "bin/claude"
    source = binary.read_text()
    start = source.index("elif role == 'teammate':")
    end = source.index("elif role == 'reviewer':", start)
    binary.write_text(source[:start] + "elif role == 'teammate':\n pass\n" + source[end:])
    result = launch(repo, env, "resume", "story-042")
    assert result.returncode == 0, result.stderr
    assert subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=tree, text=True) == head
    assert [event["role"] for event in events(seen)][-2:] == ["teammate", "reviewer"]
    state = json.loads((tmp_path / "data/plans/story-042.handoff.json").read_text())
    assert state["stages"]["executor"] == "ran"


@pytest.mark.parametrize("boundary", ["executor", "story-tier"])
def test_interrupted_stage_resumes_only_unfinished_work(tmp_path, boundary):
    from forward_progress_kill_support import interrupted_stage

    interrupted_stage(tmp_path, installed_launch(tmp_path), boundary)


def test_inherited_incomplete_candidate_executes(tmp_path):
    from completed_executor_support import completed, git, roles

    launch = installed_launch(tmp_path)
    repo, env, seen = completed(tmp_path, launch)
    tree = tmp_path / "data/worktrees/story-042"
    (tree / "src/thing.py").write_text("DONE = False\n")
    git(tmp_path, "add", "src/thing.py")
    git(tmp_path, "commit", "-qm", "incomplete inherited candidate")
    plan = tmp_path / "data/plan.md"
    plan.write_text(
        plan.read_text().replace(
            "Verify: true", "Verify: true && python3 -c 'import src.thing; assert src.thing.DONE'"
        )
    )
    count = len(events(seen))
    result = launch(repo, env, "resume", "story-042")
    assert result.returncode == 0, result.stderr
    assert roles(seen)[count:] == ["teammate", "reviewer"]


def test_unfinished_candidate_noop_is_not_certified(tmp_path):
    from completed_executor_support import completed, roles

    launch = installed_launch(tmp_path)
    repo, env, seen = completed(tmp_path, launch)
    plan = tmp_path / "data/plan.md"
    plan.write_text(
        plan.read_text().replace("Verify: true", "Verify: true && test -f required.txt")
    )
    count = len(events(seen))
    result = launch(repo, env, "resume", "story-042")
    assert result.returncode == 2, result.stderr
    assert roles(seen)[count:] == ["reviewer"]
    assert "Verify" in result.stderr
    state = json.loads((tmp_path / "data/plans/story-042.handoff.json").read_text())
    assert state["state"] == "STOPPED"


@pytest.mark.parametrize(
    "motion",
    [
        "dirty",
        "staged",
        "moved",
        "empty-commit",
        "hidden",
        "ignored",
        "untracked",
        "tier",
        "verify",
        "plan",
        "findings",
    ],
)
def test_external_inputs_invalidate_only_affected_stages(tmp_path, motion):
    from completed_executor_support import completed, damage, roles

    launch = installed_launch(tmp_path)
    repo, env, seen = completed(tmp_path, launch)
    tree = tmp_path / "data/worktrees/story-042"
    if motion == "tier":
        path = tree / ".xp/config.yml"
        path.write_text(path.read_text().replace("story: true", "story: test -f src/thing.py"))
    elif motion == "verify":
        path = tmp_path / "data/plan.md"
        path.write_text(
            path.read_text().replace("Verify: true", "Verify: true && test -f src/thing.py")
        )
    elif motion in ("plan", "findings"):
        path = (
            tmp_path
            / "data/plans"
            / ("story-042.plan.md" if motion == "plan" else "story-042.round-1.md")
        )
        if motion == "findings":
            value = json.loads(path.read_text())
            value["summary"] = "different authoritative review"
            path.write_text(json.dumps(value))
        else:
            path.write_text(path.read_text() + "changed authoritative input")
    else:
        damage(tmp_path, motion)
    count = len(events(seen))
    preview = launch(repo, env, "resume", "story-042", "--dry-run")
    if motion in ("plan", "findings"):
        result = launch(repo, env, "resume", "story-042")
        assert result.returncode == preview.returncode == 2
        assert roles(seen)[count:] == []
        assert "accepted " + motion + " changed" in result.stderr
        return
    expected = (
        "story-tier" if motion == "tier" else "reviewer" if motion == "verify" else "executor"
    )
    assert preview.returncode == 0, preview.stderr
    assert f"Next stage: {expected}." in preview.stdout
    result = launch(repo, env, "resume", "story-042")
    assert result.returncode == 0, result.stderr
    assert roles(seen)[count:] == (
        ["teammate", "reviewer"] if expected == "executor" else ["reviewer"]
    )


def test_scope_amendment_returns_to_planning(tmp_path):
    from completed_executor_support import completed, roles
    from plan_confirmation_support import amend

    launch = installed_launch(tmp_path)
    repo, env, seen = completed(tmp_path, launch)
    old_plan = (tmp_path / "data/plans/story-042.plan.md").read_bytes()
    amend(tmp_path, repo, env, launch)
    count = len(events(seen))
    result = launch(repo, env, "resume", "story-042")
    assert result.returncode == 0, result.stderr
    assert roles(seen)[count:] == ["planner", "plan-reviewer", "teammate", "reviewer"]
    assert any(
        path.read_bytes() == old_plan
        for path in (tmp_path / "data/plans/story-042.predecessors").rglob("*")
        if path.is_file()
    )


def test_stage_owned_changes_advance(tmp_path):
    from completed_executor_support import completed, roles

    launch = installed_launch(tmp_path)
    repo, env, seen = completed(tmp_path, launch)
    path = tmp_path / "data/plan.md"
    path.write_text(
        path.read_text().replace("Verify: true", "Verify: true && test -f src/thing.py")
    )
    count = len(events(seen))
    result = launch(repo, env, "resume", "story-042")
    assert result.returncode == 0, result.stderr
    assert roles(seen)[count:] == ["reviewer"]


@pytest.mark.meta
@pytest.mark.parametrize(
    "guard",
    [
        "work",
        "ignored",
        "state",
        "result",
        "publication",
        "tier-motion",
        "scope",
        "owner",
        "preview",
        "review-red",
        "evidence",
        "missing",
        "truncated",
        "checkout",
        "artifact",
        "submodule",
        "role",
        "lock",
    ],
)
def test_checkpoint_guard_detects_its_fault(tmp_path, monkeypatch, guard):
    import checkpoint_fault_support as faults
    import test_completed_executor_preview as preview
    import test_completed_executor_resume as resumed
    from plan_review_install import installed_launch as install

    target, old, new, scenario, parameter = faults.FAULTS[guard]
    control = tmp_path / "control"
    control.mkdir()
    faults.guarantee(control, scenario, parameter)
    faulty = tmp_path / "fault"
    faulty.mkdir()

    def mutated(root):
        return install(root, (old, new), target)

    monkeypatch.setitem(globals(), "installed_launch", mutated)
    monkeypatch.setattr(preview, "installed_launch", mutated)
    monkeypatch.setattr(resumed, "installed_launch", mutated)
    with pytest.raises(AssertionError):
        faults.guarantee(faulty, scenario, parameter)


def test_published_result_survives_checkpoint_interruption(tmp_path):
    from test_card_update_contract import (
        test_interrupted_spawn_resumes_exact_round_without_another_review,
    )

    test_interrupted_spawn_resumes_exact_round_without_another_review(tmp_path, "after-publication")


@pytest.mark.parametrize("damage", ["missing", "truncated", "wrong-story", "branch", "git"])
def test_refusal_preserves_work_without_success(tmp_path, damage):
    from completed_executor_support import completed, git, roles

    launch = installed_launch(tmp_path)
    repo, env, seen = completed(tmp_path, launch)
    tree = tmp_path / "data/worktrees/story-042"
    marker = tmp_path / "data/plans/story-042.handoff.json"
    saved = marker.read_bytes()
    pointer = (tree / ".git").read_bytes()
    branch = git(tmp_path, "branch", "--show-current")
    (tree / "sentinel.txt").write_text("preserved dirty evidence")
    if damage == "missing":
        marker.unlink()
    elif damage == "truncated":
        marker.write_text("{")
    elif damage == "wrong-story":
        state = json.loads(saved)
        state["checkpoint"]["story_id"] = "story-999"
        marker.write_text(json.dumps(state))
    elif damage == "branch":
        git(tmp_path, "checkout", "-q", "--detach")
    else:
        (tree / ".git").write_text("unreadable git pointer")
    files = {
        path: path.read_bytes() for path in (tmp_path / "data/plans").rglob("*") if path.is_file()
    }
    count = len(events(seen))
    result = launch(repo, env, "resume", "story-042")
    assert result.returncode == 2, result.stderr
    assert roles(seen)[count:] == []
    assert "refused" in result.stderr
    assert {path: path.read_bytes() for path in files} == files
    assert (tree / "sentinel.txt").read_text() == "preserved dirty evidence"
    marker.write_bytes(saved)
    (tree / ".git").write_bytes(pointer)
    if damage == "branch":
        git(tmp_path, "checkout", "-q", branch)
    result = launch(repo, env, "resume", "story-042")
    assert result.returncode == 0, result.stderr
    assert (tree / "sentinel.txt").read_text() == "preserved dirty evidence"


def test_submodule_runtime_motion_invalidates_executor(tmp_path):
    import subprocess

    from completed_executor_support import roles
    from plan_confirmation_support import submodule_consumer
    from spawn_helpers import set_system_md

    repo, env, seen = submodule_consumer(tmp_path, "claude")
    binary = tmp_path / "bin/claude"
    binary.write_text(
        binary.read_text().replace(
            "human_question': 'Which lease value does the human authorize?'",
            "human_question': None",
        )
    )
    excludes = tmp_path / "runtime-excludes"
    excludes.write_text("runtime.cfg\n")
    set_system_md(
        repo,
        "- Worktree bootstrap: `git -c protocol.file.allow=always submodule update --init "
        "&& printf baseline > vendor/runtime.cfg "
        f"&& git -C vendor config core.excludesfile {excludes}`",
    )
    subprocess.run(["git", "branch", "-f", "main", "HEAD"], cwd=repo, env=env, check=True)
    launch = installed_launch(tmp_path)
    first = launch(repo, env, "story-042")
    assert first.returncode == 0, first.stderr
    tree = tmp_path / "data/worktrees/story-042"
    (tree / "vendor/runtime.cfg").write_text("external runtime change")
    count = len(events(seen))
    preview = launch(repo, env, "resume", "story-042", "--dry-run")
    assert preview.returncode == 0 and "Next stage: executor." in preview.stdout, preview.stderr
    result = launch(repo, env, "resume", "story-042")
    assert result.returncode == 0, result.stderr
    assert roles(seen)[count:] == ["teammate", "reviewer"]
