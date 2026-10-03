"""Plan artifacts survive replacement; only explicit amendments buy new planning."""

import json

import pytest
from completed_executor_support import completed, roles
from plan_confirmation_support import amend, consumer, events
from plan_review_install import installed_launch


def test_amendment_preserves_prior_plan_and_findings(tmp_path):
    launch = installed_launch(tmp_path)
    repo, env, seen = completed(tmp_path, launch)
    plans = tmp_path / "data/plans"
    old = [(plans / name).read_bytes() for name in ("story-042.plan.md", "story-042.round-1.md")]
    amend(tmp_path, repo, env, launch)
    count = len(events(seen))
    result = launch(repo, env, "resume", "story-042")
    assert result.returncode == 0, result.stderr
    state = json.loads((plans / "story-042.handoff.json").read_text())
    assert state["predecessors"]
    preserved = [
        path.read_bytes()
        for path in (plans / "story-042.predecessors").rglob("*")
        if path.is_file()
    ]
    assert all(body in preserved for body in old)
    assert roles(seen)[count:] == ["planner", "plan-reviewer", "teammate", "reviewer"]


@pytest.mark.parametrize("artifact", ["receipt", "candidate", "plan", "findings"])
def test_missing_authoritative_binding_refuses_without_launch(tmp_path, artifact):
    launch = installed_launch(tmp_path)
    repo, env, seen = completed(tmp_path, launch)
    plans = tmp_path / "data/plans"
    paths = {
        "receipt": "story-042.round-1.acceptance.json",
        "candidate": "story-042.round-1.card.md",
        "plan": "story-042.plan.md",
        "findings": "story-042.round-1.md",
    }
    (plans / paths[artifact]).unlink()
    count = len(events(seen))
    result = launch(repo, env, "resume", "story-042")
    assert result.returncode == 2, result.stderr
    assert roles(seen)[count:] == []


def test_reason_only_amendment_does_not_waive_question(tmp_path):
    launch = installed_launch(tmp_path)
    repo, env, seen = consumer(tmp_path)
    first = launch(repo, env, "story-042")
    assert first.returncode == 2
    assert (
        launch(repo, env, "amend", "story-042", "--reason", "still needs a human answer").returncode
        == 0
    )
    result = launch(repo, env, "resume", "story-042")
    assert result.returncode == 2
    assert "teammate" not in roles(seen)
