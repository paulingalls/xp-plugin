"""Every shipped skill and PROCESS route is reachable at its action site."""

import re
import shlex
import subprocess
import sys
from pathlib import Path

import pytest
from close_free_card_cases import free_identity
from close_helpers import PLUGIN, close, make_repo

CREATE_SPRINT = PLUGIN / "skills" / "create-sprint" / "SKILL.md"
SPRINT_CLOSE = PLUGIN / "skills" / "sprint-close" / "SKILL.md"
PLAN_TEMPLATE = PLUGIN / "templates" / "plan.md"


def _step_regions(process):
    blocks = re.findall(r"(?ms)^((\d+)\. \*\*[^*]+\*\*.*?)(?=^\d+\. \*\*|\Z)", process)
    steps = {int(number): body for body, number in blocks}
    assert sorted(steps) == [1, 2, 3, 4, 5], sorted(steps)
    return steps


def _command_words(span):
    """A code span as [script, *args], or None if it names no script. The script is
    the first `.py` WORD and not the first word: xp-setup routes through
    `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/setup.py`, and an interpreter prefix is
    exactly the spelling a first-word check drops silently — an unwalked command
    that reads as covered.
    """
    try:
        words = shlex.split(span)
    except ValueError:
        return None
    for index, word in enumerate(words):
        if word.endswith(".py"):
            return [Path(word).name, *words[index + 1 :]]
    return None


def _walk_command(command):
    """ONE walker for every shipped spelling, PROCESS step or skill body alike. A
    second copy drifts off the usage assertion below, and that assertion is the only
    half of the walk that catches a misspelling.
    """
    words = _command_words(command)
    assert words, f"{command} names no script"
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
        routes = [s for s in spans if s.startswith("/") or _command_words(s)]
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
    references = set(token.findall("\n".join([process, *prose_docs, *nudges, *refusals])))
    unknown = sorted(references - set(shipped))
    assert not unknown, f"named but not shipped: {', '.join(unknown)}"


def _assert_template_owns_card_fields(skill, template):
    fields = ("# Roadmap", "Context:", "Files:", "AC:", "Verify:", "Close review:")
    missing = [field for field in fields if field not in template]
    assert not missing, f"plan template is missing: {', '.join(missing)}"
    # `Verify:` exactly, not "at most one field": the budget is one because the skill
    # teaches the grammar the template cannot carry, so a count alone lets a later edit
    # spend it on a different field. A second field is the shape drifting into prose;
    # none means the grammar no longer names the field it governs.
    restated = [field for field in fields if field in skill]
    assert restated == ["Verify:"], f"create-sprint restates {restated}, not ['Verify:']"


def _assert_authoring_content(skill, closing):
    """The skill's own list, pinned as vocabulary. No harness reaches the judgment
    behind it, so the reachable failure is a later edit trimming an item to buy
    words against the skill's word cap — which is silent and looks like tightening.
    """
    for token in ("`sprint_cap`", "`debt_budget`", "merge order", "collisions", "argv", "`cd`"):
        assert token in skill, f"create-sprint no longer names {token}"
    for token in ("slate_review.py", "close.py sprint <id> start", "`spawn.py ready"):
        assert token in skill, f"create-sprint no longer names {token}"
    assert skill.index("slate_review.py") < skill.index("close.py sprint <id> start"), (
        "slate review must precede sprint start"
    )
    assert skill.index("close.py sprint <id> start") < skill.index("`spawn.py ready"), (
        "sprint start must precede spawn ready"
    )
    for token in ("slate_review.py", "git switch", "Open the sprint"):
        assert token not in closing, f"sprint-close still opens via {token}"


def _walk_skill_commands(skills_dir):
    """EVERY shipped skill, enumerated from the directory rather than hand-listed, so
    a skill added later is walked without editing this test (bug 6d384ef9). Only
    create-sprint's body was walked before; the other four skills' spellings were
    pinned as literal substrings, which greens on a command that no longer exists.

    The per-skill vacuity guard is derived from the file, never a count: a body that
    mentions `.py` at all must yield a command, so the span regex silently matching
    nothing reds instead of walking an empty list.
    """
    for skill in sorted(skills_dir.glob("*/SKILL.md")):
        text = skill.read_text()
        commands = dict.fromkeys(s for s in re.findall(r"`([^`]+)`", text) if _command_words(s))
        assert commands or ".py" not in text, f"{skill.parent.name} names no command to walk"
        for command in commands:
            _walk_command(command)


def _copied_skills(root, edit):
    """Fault injection against a COPY of the shipped bodies, so each arm proves the
    walk reds on the real prose rather than on a fixture shaped like it."""
    for skill in sorted((PLUGIN / "skills").glob("*/SKILL.md")):
        target = root / skill.parent.name / "SKILL.md"
        target.parent.mkdir(parents=True)
        target.write_text(edit(skill.read_text()))
    return root


def test_each_loop_step_names_its_command_or_skill():
    process = (PLUGIN / "PROCESS.md").read_text()
    _walk_step_routes(process)
    with pytest.raises(AssertionError, match=r"missing\.py"):
        _walk_step_routes(process.replace("plan_review.py", "missing.py"))
    with pytest.raises(AssertionError, match="redy"):
        _walk_step_routes(process.replace("spawn.py ready", "spawn.py redy"))
    with pytest.raises(AssertionError, match="step 2 names no"):
        _walk_step_routes(process.replace("`spawn.py <story-id>`", "spawn.py"))


def test_the_template_owns_the_card_field_list():
    skill = CREATE_SPRINT.read_text()
    template = PLAN_TEMPLATE.read_text()
    _assert_template_owns_card_fields(skill, template)
    for field in ("# Roadmap", "Context:", "Files:", "AC:", "Verify:", "Close review:"):
        with pytest.raises(AssertionError, match="plan template is missing"):
            _assert_template_owns_card_fields(skill, template.replace(field, "omitted", 1))
    duplicate = skill + "\n# Roadmap\nContext:\nFiles:\nAC:\nVerify:\nClose review:\n"
    with pytest.raises(AssertionError, match="restates"):
        _assert_template_owns_card_fields(duplicate, template)
    with pytest.raises(AssertionError, match="restates"):
        _assert_template_owns_card_fields(
            skill + "\nEach card carries Context: and AC:\n", template
        )
    # the word-saving rewrite a count-only guard greens: the grammar survives, the
    # field name it governs does not, and the skill stops teaching which line to write
    with pytest.raises(AssertionError, match="restates"):
        _assert_template_owns_card_fields(skill.replace("each `Verify:`", "every check"), template)


def test_create_sprint_carries_what_the_template_cannot():
    skill = CREATE_SPRINT.read_text()
    closing = SPRINT_CLOSE.read_text()
    _assert_authoring_content(skill, closing)
    for token in ("`sprint_cap`", "`debt_budget`", "merge order", "collisions", "argv", "`cd`"):
        with pytest.raises(AssertionError, match="no longer names"):
            _assert_authoring_content(skill.replace(token, "the slate"), closing)
    # same words, order destroyed: the ordering claim must red on its own
    with pytest.raises(AssertionError, match="precede"):
        _assert_authoring_content("\n".join(reversed(skill.split("\n"))), closing)
    with pytest.raises(AssertionError, match="still opens"):
        _assert_authoring_content(skill, closing + "\nOpen the sprint with slate_review.py")


def test_every_shipped_skill_command_is_walkable(tmp_path):
    _walk_skill_commands(PLUGIN / "skills")
    unspanned = _copied_skills(tmp_path / "a", lambda t: re.sub(r"`([^`]*\.py[^`]*)`", r"\1", t))
    with pytest.raises(AssertionError, match="names no command"):
        _walk_skill_commands(unspanned)
    absent = _copied_skills(tmp_path / "b", lambda t: t.replace("close.py", "missing.py"))
    with pytest.raises(AssertionError, match="does not resolve"):
        _walk_skill_commands(absent)
    redy = lambda t: t.replace("spawn.py ready", "spawn.py redy")  # noqa: E731
    misspelled = _copied_skills(tmp_path / "c", redy)
    with pytest.raises(AssertionError, match="answered as"):
        _walk_skill_commands(misspelled)
    # the arm that reds ONLY because the script is found past an interpreter prefix:
    # on a first-word selector xp-setup's span yields nothing and this greens
    gone = lambda t: t.replace("scripts/setup.py", "scripts/gone.py")  # noqa: E731
    prefixed = _copied_skills(tmp_path / "d", gone)
    with pytest.raises(AssertionError, match="does not resolve"):
        _walk_skill_commands(prefixed)


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

    with pytest.raises(AssertionError, match="not-shipped"):
        _assert_skill_routes(
            skills,
            process.replace("`/free-close`", "`/not-shipped`"),
            prose_docs,
            nudges,
            refusals,
        )
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
