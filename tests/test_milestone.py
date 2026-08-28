import shlex
import sys

import pytest
from sprint_helpers import PLUGIN, make_repo, sprint

PLAN = """# plan
## Milestone 2 repeats Milestone 20   [planned]
Goal: first.
Done when: true
### Sprint 2
#### story-002 — shipped   [done]
### Sprint 20
#### story-020 — retired   [retired]
### Parking — not scheduled
#### story-200 — later   [planned]

## Milestone 2 repeats Milestone 20   extended   [planned]
Goal: second.
Done when: true
### Sprint 3
#### story-003 — later   [in-progress]
"""


def active_plan(condition="true"):
    return PLAN.replace(
        "## Milestone 2 repeats Milestone 20   [planned]",
        "## Milestone 2 repeats Milestone 20   [in-progress]",
    ).replace("Done when: true", f"Done when: {condition}", 1)


def condition(tmp_path):
    sentinel = tmp_path / "condition-ran"
    script = tmp_path / "condition.py"
    script.write_text(
        "import pathlib, sys\n"
        "assert sys.argv[1] == 'fixed value'\n"
        f"pathlib.Path({str(sentinel)!r}).write_text('green')\n"
    )
    return shlex.join([sys.executable, str(script), "fixed value"]), sentinel


def reopen(path):
    before = "story-002 — shipped   [done]"
    after = "story-002 — shipped   [in-progress]"
    path.write_text(path.read_text().replace(before, after))


def test_plan_template_leaves_milestone_start_to_the_pipeline():
    template = (PLUGIN / "templates" / "plan.md").read_text()
    assert "## Milestone 1 — <name>   [planned]" in template


def test_sprint_membership_does_not_require_an_enclosing_milestone():
    from sprint_close import milestone

    plan = "### Sprint 2\n#### story-002 — scheduled   [done]\n"
    assert milestone.sprint_stories(plan, "2") == ["#### story-002 — scheduled   [done]"]


def test_lookup_owns_the_exact_sprint_and_only_scheduled_cards():
    from sprint_close import milestone

    found = milestone.find(PLAN, "2")
    assert found.heading == "## Milestone 2 repeats Milestone 20   "
    assert found.status == "planned"
    assert found.members == [
        "#### story-002 — shipped   [done]",
        "#### story-020 — retired   [retired]",
    ]
    assert all("story-200" not in member for member in found.members)
    assert milestone.find(PLAN, "20").heading == found.heading
    assert milestone.find(PLAN, "3").heading == "## Milestone 2 repeats Milestone 20   extended   "


def test_opening_the_first_sprint_starts_only_its_milestone(tmp_path):
    repo, env, _g = make_repo(tmp_path, plan=PLAN)
    branch = tmp_path / "data" / "sprint_branch"
    branch.unlink()

    opened = sprint(repo, env, "start")
    assert opened.returncode == 0, opened.stderr
    plan = (tmp_path / "data" / "plan.md").read_text()
    assert "## Milestone 2 repeats Milestone 20   [in-progress]" in plan
    assert "## Milestone 2 repeats Milestone 20   extended   [planned]" in plan

    before = plan
    later = sprint(repo, env, "start", sprint_id="3")
    assert later.returncode == 2 and "story-003" in later.stderr
    assert (tmp_path / "data" / "plan.md").read_text() == before


def test_milestone_done_runs_declared_argv_then_flips_only_its_heading(tmp_path):
    command, sentinel = condition(tmp_path)
    plan = active_plan(command).replace(
        "## Milestone 2 repeats Milestone 20   extended   [planned]",
        "## Milestone 2 repeats Milestone 20   extended   [in-progress]",
    )
    repo, env, _g = make_repo(tmp_path, plan=plan)

    result = sprint(repo, env, "milestone-done")

    assert result.returncode == 0, result.stderr
    assert sentinel.read_text() == "green"
    changed = (tmp_path / "data" / "plan.md").read_text()
    assert "## Milestone 2 repeats Milestone 20   [done]" in changed
    assert "## Milestone 2 repeats Milestone 20   extended   [in-progress]" in changed


@pytest.mark.parametrize(
    "declared",
    [None, "", "true; touch SHELL-PAYLOAD", "cd /", "missing-milestone-command", "false"],
)
def test_milestone_done_refuses_invalid_or_red_done_when(tmp_path, declared):
    plan = active_plan(declared or "")
    if declared is None:
        plan = plan.replace("Done when: \n", "")
    elif declared == "":
        plan = plan.replace("Done when: \n", "Done when:\nThis prose is not a command.\n")
    repo, env, _g = make_repo(tmp_path, plan=plan)

    result = sprint(repo, env, "milestone-done")

    assert result.returncode == 2
    assert "Done when:" in result.stderr
    assert (
        "## Milestone 2 repeats Milestone 20   [in-progress]"
        in (tmp_path / "data" / "plan.md").read_text()
    )
    assert not (repo / "SHELL-PAYLOAD").exists()


def test_milestone_done_rechecks_terminal_cards_before_running(tmp_path):
    command, sentinel = condition(tmp_path)
    repo, env, _g = make_repo(tmp_path, plan=active_plan(command))
    proposed = sprint(repo, env, "start")
    assert "close.py sprint 2 milestone-done" in proposed.stdout
    path = tmp_path / "data" / "plan.md"
    reopen(path)

    result = sprint(repo, env, "milestone-done")

    assert result.returncode == 2 and not sentinel.exists()
    assert "[in-progress]" in path.read_text()


def test_locked_flip_rechecks_after_the_condition_succeeds(tmp_path, monkeypatch, capsys):
    command, sentinel = condition(tmp_path)
    repo, env, _g = make_repo(tmp_path, plan=active_plan(command))
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    monkeypatch.chdir(repo)
    import work
    from sprint_close import milestone

    path = tmp_path / "data" / "plan.md"

    def race(mutate):
        reopen(path)
        return work.edit_plan(mutate)

    monkeypatch.setattr(milestone, "edit_plan", race)
    assert milestone.cmd_done("2") == 2
    assert sentinel.read_text() == "green"
    assert "changed" in capsys.readouterr().err
    assert "## Milestone 2 repeats Milestone 20   [in-progress]" in path.read_text()
