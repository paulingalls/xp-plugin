"""Actual publication checks still bind the plan review to measured inputs."""

import pytest
from plan_confirmation_support import consumer, events, late_launch
from spawn_helpers import spawn


@pytest.mark.parametrize("mutant", [False, pytest.param(True, marks=pytest.mark.meta)])
def test_publication_guard_detects_motion_inside_card_application(tmp_path, mutant):
    repo, env, seen = consumer(tmp_path, initial_status="clean", initial_question=None)
    assert spawn(repo, env, "story-042").returncode != 0
    assert spawn(repo, env, "amend", "story-042", "--reason", "fresh approval").returncode == 0
    (tmp_path / "executor-stop").unlink()
    mutation = ("if source_check:", "if False:") if mutant else None
    launch = late_launch(tmp_path, None, publication=True)
    if mutation:
        target = tmp_path / "cache/xp-plugin/fixture/scripts/plan_acceptance.py"
        target.write_text(target.read_text().replace(*mutation))
    result = launch(repo, env, "resume", "story-042")

    def guarantee():
        assert result.returncode != 0, result.stderr
        assert not any(event["role"] == "teammate" for event in events(seen))

    if mutant:
        with pytest.raises(AssertionError):
            guarantee()
    else:
        guarantee()


@pytest.mark.parametrize("target", ["card", "credential", "findings", "tree"])
def test_launch_rechecks_inputs_after_prompt_composition(tmp_path, target):
    from plan_confirmation_support import consumer, late_launch

    repo, env, seen = consumer(tmp_path, initial_status="clean", initial_question=None)
    assert spawn(repo, env, "story-042").returncode != 0
    (tmp_path / "executor-stop").unlink()
    launch = late_launch(tmp_path, target)
    result = launch(repo, env, "resume", "story-042")
    if target == "tree":
        assert result.returncode == 0, result.stderr
        return
    assert result.returncode == 2, result.stderr
    assert not any(event["role"] == "teammate" for event in events(seen))


def test_publication_accepts_authorized_card_edit(tmp_path):
    import json

    from completed_executor_support import roles
    from plan_review_install import installed_launch

    repo, env, seen = consumer(tmp_path, initial_status="edited", initial_question=None)
    (tmp_path / "executor-stop").unlink()
    binary = tmp_path / "bin/claude"
    old = "elif role == 'plan-reviewer':"
    binary.write_text(
        binary.read_text().replace(
            old,
            old
            + "\n candidate = re.search(r'^CARD_CANDIDATE_PATH: (.+)$', prompt, re.M).group(1)\n"
            " text = open(candidate).read().replace('src/other.py', 'src/other.py, README.md')\n"
            " text = text.replace('Verify: true', 'Verify: true && true')\n"
            " open(candidate, 'w').write(text)",
        )
    )
    result = installed_launch(tmp_path)(repo, env, "story-042")
    assert result.returncode == 0, result.stderr
    record = json.loads((tmp_path / "data/plans/story-042.round-1.acceptance.json").read_text())
    credential = json.loads((tmp_path / "data/markers/story-042.ready.json").read_text())
    assert record["before"] != record["after"]
    assert credential["digest"] == record["digest"]
    assert credential["card"] == record["after"]
    assert record["after"] in (tmp_path / "data/plan.md").read_text()
    assert roles(seen) == ["planner", "plan-reviewer", "teammate", "reviewer"]
