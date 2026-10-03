"""Resume preserves independent candidate checks after retiring completion certificates."""

import json

import pytest
from completed_executor_support import completed, roles
from plan_confirmation_support import consumer, events
from plan_review_install import installed_launch


def test_reuse_preserves_commit_attribution(tmp_path):
    from completed_executor_support import git

    launch = installed_launch(tmp_path)
    repo, env, seen = completed(tmp_path, launch)
    head = git(tmp_path, "rev-parse", "HEAD")
    count = len(events(seen))
    result = launch(repo, env, "resume", "story-042")
    assert result.returncode == 0, result.stderr
    assert git(tmp_path, "rev-parse", "HEAD") == head
    assert roles(seen)[count:] == ["reviewer"]


@pytest.mark.parametrize("kind", ["STOPPED", "FINISHED"])
def test_legacy_handback_runs_executor(tmp_path, kind):
    launch = installed_launch(tmp_path)
    repo, env, seen = completed(tmp_path, launch)
    path = tmp_path / "data/plans/story-042.handoff.json"
    state = json.loads(path.read_text())
    state.pop("checkpoint")
    state["state"] = kind
    path.write_text(json.dumps(state))
    count = len(events(seen))
    result = launch(repo, env, "resume", "story-042")
    assert result.returncode == 0, result.stderr
    assert roles(seen)[count:] == ["teammate", "reviewer"]


def test_hidden_uncommitted_executor_bytes_cannot_certify(tmp_path):
    from completed_executor_support import hidden_handback

    repo, env, _ = hidden_handback(tmp_path)
    result = installed_launch(tmp_path)(repo, env, "story-042")
    assert result.returncode == 2, result.stderr
    assert "tracked executor bytes differ" in result.stderr
    state = json.loads((tmp_path / "data/plans/story-042.handoff.json").read_text())
    assert state["stages"]["executor"] == "running"
    assert state["state"] == "STOPPED"


@pytest.mark.parametrize("command", ["false", "EDIT-ME", "missing-tier-binary"])
def test_non_green_tier_is_not_recorded_as_passed(tmp_path, command):
    from completed_executor_support import tier_consumer

    repo, env, _ = tier_consumer(tmp_path, command)
    result = installed_launch(tmp_path)(repo, env, "story-042")
    state = json.loads((tmp_path / "data/plans/story-042.handoff.json").read_text())
    assert state["stages"]["story-tier"] == ("skipped" if command == "EDIT-ME" else "failed")
    assert result.returncode == (0 if command == "EDIT-ME" else 2)


def test_tier_motion_cannot_publish_success(tmp_path):
    from completed_executor_support import tier_consumer

    repo, env, _ = tier_consumer(tmp_path, "printf changed >> src/thing.py")
    result = installed_launch(tmp_path)(repo, env, "story-042")
    assert result.returncode == 2, result.stderr
    assert "inputs moved" in result.stderr
    state = json.loads((tmp_path / "data/plans/story-042.handoff.json").read_text())
    assert state["checkpoint"]["results"]["story-tier"]["result"] == "failed"


def test_unfinished_executor_remains_interrupted_even_after_commit(tmp_path):
    repo, env, seen = consumer(tmp_path, initial_status="clean", initial_question=None)
    (tmp_path / "executor-stop").unlink()
    binary = tmp_path / "bin/claude"
    source = binary.read_text().replace(
        "elif role == 'reviewer':",
        " with open(seen, 'a') as f: f.write(json.dumps(event) + '\\n')\n"
        " sys.exit(1)\nelif role == 'reviewer':",
    )
    binary.write_text(source)
    result = installed_launch(tmp_path)(repo, env, "story-042")
    assert result.returncode != 0
    assert roles(seen) == ["planner", "plan-reviewer", "teammate"]
    state = json.loads((tmp_path / "data/plans/story-042.handoff.json").read_text())
    assert state["checkpoint"]["results"]["executor"]["result"] == "interrupted"


def test_failed_acceptance_requires_execution_before_retry(tmp_path):
    launch = installed_launch(tmp_path)
    repo, env, seen = completed(tmp_path, launch)
    plan = tmp_path / "data/plan.md"
    plan.write_text(
        plan.read_text().replace("Verify: true", "Verify: true && test -f required.txt")
    )
    failed = launch(repo, env, "resume", "story-042")
    assert failed.returncode == 2, failed.stderr
    binary = tmp_path / "bin/claude"
    binary.write_text(
        binary.read_text().replace(
            "elif role == 'teammate':",
            "elif role == 'teammate':\n open('required.txt', 'w').write('repaired requirement')",
        )
    )
    count = len(events(seen))
    recovered = launch(repo, env, "resume", "story-042")
    assert recovered.returncode == 2, recovered.stderr
    assert roles(seen)[count:] == []
    assert not (tmp_path / "data/worktrees/story-042/required.txt").exists()
