"""Every shipped skill and PROCESS route is reachable at its action site."""

import re
import shlex
import subprocess
import sys

import pytest
from close_free_card_cases import free_identity
from close_helpers import PLUGIN, close, make_repo

CREATE_SPRINT = PLUGIN / "skills" / "create-sprint" / "SKILL.md"
PLAN_TEMPLATE = PLUGIN / "templates" / "plan.md"


def _step_regions(process):
    blocks = re.findall(r"(?ms)^((\d+)\. \*\*[^*]+\*\*.*?)(?=^\d+\. \*\*|\Z)", process)
    steps = {int(number): body for body, number in blocks}
    assert sorted(steps) == [1, 2, 3, 4, 5], sorted(steps)
    return steps


def _walk_command(command):
    """ONE walker for every shipped spelling, PROCESS step or skill body alike. A
    second copy drifts off the usage assertion below, and that assertion is the only
    half of the walk that catches a misspelling.
    """
    words = shlex.split(command)
    script = PLUGIN / "scripts" / words[0]
    assert script.is_file(), f"{command} does not resolve"
    argv = ["walk" if word.startswith("<") else word for word in words]
    result = subprocess.run(
        [sys.executable, str(script), *argv[1:], "--help"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"{command} does not answer --help: {result.stderr}"
    # spawn.py accepts a story id at the top level, so an unknown subcommand
    # can exit zero unless the requested spelling is present in its usage.
    usage = result.stdout.split("\n\n", 1)[0]
    named = [word for word in words[1:] if not word.startswith("<")]
    assert all(word in usage for word in named), f"{command} answered as `{usage}`"


def _walk_step_routes(process):
    for number, step in _step_regions(process).items():
        spans = re.findall(r"`([^`]+)`", step)
        routes = [s for s in spans if s.startswith("/") or shlex.split(s)[0].endswith(".py")]
        assert routes, f"step {number} names no command or skill"
        for route in (r for r in routes if not r.startswith("/")):
            _walk_command(route)


def _assert_skill_routes(skills_dir, process, prose_docs, nudges, refusals):
    shipped = sorted(d.name for d in skills_dir.iterdir() if (d / "SKILL.md").is_file())
    assert shipped, "no skills found — the enumeration itself broke"
    token = re.compile(r"`/([a-z][a-z0-9-]+)`")
    action_tokens = set(
        token.findall("\n".join([*_step_regions(process).values(), *nudges, *refusals]))
    )
    missing = sorted(set(shipped) - action_tokens)
    assert not missing, f"shipped but named at no action site: {', '.join(missing)}"
    references = set(token.findall("\n".join([*prose_docs, *nudges, *refusals])))
    unknown = sorted(references - set(shipped))
    assert not unknown, f"named but not shipped: {', '.join(unknown)}"


def _assert_template_owns_card_fields(skill, template):
    fields = ("# Execution Plan", "Context:", "Files:", "AC:", "Verify:", "Close review:")
    missing = [field for field in fields if field not in template]
    assert not missing, f"plan template is missing: {', '.join(missing)}"
    # one is the budget, not zero: the skill teaches the `Verify:` grammar, which the
    # template cannot carry. Restating a SECOND field is the shape drifting into prose.
    duplicated = [field for field in fields if field in skill]
    assert len(duplicated) <= 1, f"create-sprint duplicates the template's fields: {duplicated}"


def _assert_authoring_content(skill):
    """The skill's own list, pinned as vocabulary. No harness reaches the judgment
    behind it, so the reachable failure is a later edit trimming an item to buy
    words against the skill's word cap — which is silent and looks like tightening.
    """
    for token in ("`sprint_cap`", "`debt_budget`", "merge order", "collisions", "argv", "`cd`"):
        assert token in skill, f"create-sprint no longer names {token}"
    assert "`/sprint-close`" in skill and "`spawn.py ready" in skill
    assert skill.index("`/sprint-close`") < skill.index("`spawn.py ready"), (
        "slate review must precede any `spawn.py ready`"
    )


def _walk_skill_commands(skill):
    spans = re.findall(r"`([^`]+)`", skill)
    commands = [span for span in spans if shlex.split(span)[0].endswith(".py")]
    assert commands, "create-sprint names no command to walk"
    for command in commands:
        _walk_command(command)


def test_each_loop_step_names_its_command_or_skill():
    process = (PLUGIN / "PROCESS.md").read_text()
    _walk_step_routes(process)
    with pytest.raises(AssertionError, match=r"missing\.py"):
        _walk_step_routes(process.replace("plan_review.py", "missing.py"))
    with pytest.raises(AssertionError, match="bogus"):
        _walk_step_routes(process.replace("close.py free", "close.py bogus"))
    with pytest.raises(AssertionError, match="redy"):
        _walk_step_routes(process.replace("spawn.py ready", "spawn.py redy"))
    with pytest.raises(AssertionError, match="step 2 names no"):
        _walk_step_routes(process.replace("`spawn.py <story-id>`", "spawn.py"))


def test_the_template_owns_the_card_field_list():
    skill = CREATE_SPRINT.read_text()
    template = PLAN_TEMPLATE.read_text()
    _assert_template_owns_card_fields(skill, template)
    for field in ("# Execution Plan", "Context:", "Files:", "AC:", "Verify:", "Close review:"):
        with pytest.raises(AssertionError, match="plan template is missing"):
            _assert_template_owns_card_fields(skill, template.replace(field, "omitted", 1))
    duplicate = skill + "\n# Execution Plan\nContext:\nFiles:\nAC:\nVerify:\nClose review:\n"
    with pytest.raises(AssertionError, match="duplicates"):
        _assert_template_owns_card_fields(duplicate, template)
    with pytest.raises(AssertionError, match="duplicates"):
        _assert_template_owns_card_fields(
            skill + "\nEach card carries Context: and AC:\n", template
        )


def test_create_sprint_carries_what_the_template_cannot():
    skill = CREATE_SPRINT.read_text()
    _assert_authoring_content(skill)
    for token in ("`sprint_cap`", "`debt_budget`", "merge order", "collisions", "argv", "`cd`"):
        with pytest.raises(AssertionError, match="no longer names"):
            _assert_authoring_content(skill.replace(token, "the slate"))
    # same words, order destroyed: the ordering claim must red on its own
    with pytest.raises(AssertionError, match="precede"):
        _assert_authoring_content("\n".join(reversed(skill.split("\n"))))


def test_every_create_sprint_command_is_walkable():
    skill = CREATE_SPRINT.read_text()
    _walk_skill_commands(skill)
    without_commands = re.sub(r"`[^`]*\.py[^`]*`", "the command", skill)
    with pytest.raises(AssertionError, match="names no command"):
        _walk_skill_commands(without_commands)
    with pytest.raises(AssertionError, match="does not resolve"):
        _walk_skill_commands(skill.replace("spawn.py", "missing.py"))
    with pytest.raises(AssertionError, match="answered as"):
        _walk_skill_commands(skill.replace("spawn.py ready", "spawn.py redy"))


def test_every_shipped_skill_is_named_by_shipped_prose(tmp_path):
    """A skill nothing points at is reachable only by someone who already knows it
    exists, which is the opposite of what a skill is for. Measured: /sprint-close
    and /xp-setup shipped for six sprints named by no prose, and the lead ran the
    scripts they wrap for seven story closes and one sprint close — skipping, both
    times, the judgment step the skill reserves and the script cannot enforce.

    Enumerated from the directory, never a hand-list: a skill added later is
    covered without editing this test (bug 6d384ef9).
    """
    story_root = tmp_path / "story"
    story_root.mkdir()
    repo, env, _g = make_repo(story_root)
    assert close(repo, env, "review").returncode == 0
    story_nudge = close(repo, env, "land")
    assert story_nudge.returncode == 0 and story_nudge.stdout, story_nudge.stderr

    from sprint_helpers import make_repo as make_sprint_repo
    from sprint_helpers import sprint

    sprint_root = tmp_path / "sprint"
    sprint_root.mkdir()
    repo, env, g = make_sprint_repo(sprint_root)
    g("tag", "v0.2.1")
    g("checkout", "-q", "main")
    g("merge", "-q", "--no-ff", "sprint-002", "-m", "release")
    sprint_nudge = sprint(repo, env, "post-merge")
    assert sprint_nudge.returncode == 0 and sprint_nudge.stdout, sprint_nudge.stderr

    from spawn_helpers import make_repo as make_spawn_repo
    from spawn_helpers import spawn, stub_claude
    from test_close_free import carded_free_patch

    free_root = tmp_path / "free"
    repo, env, g = carded_free_patch(free_root)
    stub_claude(free_root)
    free_nudge = spawn(repo, env, free_identity(g)[1])
    assert free_nudge.returncode == 0 and free_nudge.stdout, free_nudge.stderr

    spawn_root = tmp_path / "spawn"
    spawn_root.mkdir()
    repo, env, _g = make_spawn_repo(spawn_root, executor="claude/haiku")
    stub_claude(spawn_root)
    (repo / ".xp").rename(repo / "held-xp")
    refusal = spawn(repo, env, "story-042")
    assert refusal.returncode == 2 and "no .xp/" in refusal.stderr

    skills = PLUGIN / "skills"
    process = (PLUGIN / "PROCESS.md").read_text()
    prose_docs = [path.read_text() for path in PLUGIN.rglob("*.md")]
    nudges = [story_nudge.stdout, sprint_nudge.stdout, free_nudge.stdout]
    refusals = [refusal.stderr]
    _assert_skill_routes(skills, process, prose_docs, nudges, refusals)

    mention_only = process.replace("`/story-close`", "the story skill").replace(
        "`/sprint-close`", "the sprint skill"
    )
    mention_only = "`/story-close` and `/sprint-close` are skills.\n" + mention_only
    with pytest.raises(AssertionError, match="action site"):
        _assert_skill_routes(skills, mention_only, prose_docs, nudges, refusals)

    copied_skills = tmp_path / "skills"
    for skill in (d for d in skills.iterdir() if (d / "SKILL.md").is_file()):
        (copied_skills / skill.name).mkdir(parents=True)
        (copied_skills / skill.name / "SKILL.md").write_text("")
    (copied_skills / "unrouted" / "SKILL.md").parent.mkdir()
    (copied_skills / "unrouted" / "SKILL.md").write_text("")
    with pytest.raises(AssertionError, match="unrouted"):
        _assert_skill_routes(copied_skills, process, prose_docs, nudges, refusals)
    with pytest.raises(AssertionError, match="not-shipped"):
        _assert_skill_routes(
            skills, process, [*prose_docs, "Use `/not-shipped`."], nudges, refusals
        )
    with pytest.raises(AssertionError, match="not-shipped"):
        _assert_skill_routes(
            skills, process, prose_docs, [*nudges, "Next: `/not-shipped`."], refusals
        )
