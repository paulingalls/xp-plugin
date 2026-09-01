"""The sprint slate reaches an independent reader before any story slot is spent."""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
PLUGIN = ROOT / "plugins" / "xp-plugin"
CHARTER = PLUGIN / "agents" / "card-reviewer.md"
SKILL = PLUGIN / "skills" / "sprint-close" / "SKILL.md"
PROCESS = PLUGIN / "PROCESS.md"
DESIGN = ROOT / "docs" / "DESIGN.md"
DESIGN_CLAIMS = (
    "four review points",
    "Claude Code lead",
    "Codex lead cannot invoke",
    "multi-file",
    "AFTER `spawn.py ready`",
    "single-file",
    "skipped review leaves no record",
    "three needed the later tree",
    "four needed the whole slate",
    "all five earned",
    "work.md",
    "repo-local citation checker is affordable",
)


def section(text, heading, next_heading):
    return text.split(heading, 1)[1].split(next_heading, 1)[0]


def numbered_items(text):
    return {
        label: body
        for label, body in re.findall(
            r"^\d+\. \*\*(.+?)\*\*(.*?)(?=^\d+\. \*\*|\Z)", text, re.M | re.S
        )
    }


def assert_open_route(skill, process):
    opening = section(skill, "0. **", "1. **")
    card_step = section(process, "1. **Card review**", "2. **Story**")
    assert opening.index("card-reviewer") < opening.index("close.py sprint <id> start")
    assert "full proposed slate" in opening and "`sprint_cap`" in opening
    assert "author's conclusions" in opening and "do not give" in opening
    assert "corrected cards" in opening and "work.py note" in opening
    assert "`/sprint-close`" in card_step and "corrected slate" in card_step
    assert card_step.index("`/sprint-close`") < card_step.index("spawn.py ready")


def assert_charter_contract(charter):
    checks = numbered_items(section(charter, "## Checks", "## Output"))
    assert set(checks) == {
        "Slate",
        "Acceptance",
        "Premises",
        "Omitted pins",
        # sprint-015 retro promotion: story-089's first teammate stopped and escalated,
        # and its Verify said nothing about whether the escalation was correct.
        "Stop states",
        "Mutation",
    }
    assert all(word in checks["Slate"] for word in ("order", "funding", "collisions", "capacity"))
    assert "execute" in checks["Premises"] and "reachable" in checks["Premises"]
    assert "search" in checks["Omitted pins"] and "card does not name" in checks["Omitted pins"]
    assert "disposable copy" in checks["Mutation"] and "acceptance" in checks["Mutation"]
    output = charter.split("## Output", 1)[1]
    assert "one `## <story-id> — RED|GREEN`" in output
    assert "falsified premise" in output and "checked evidence" in output
    assert "## Slate — RED|GREEN" in output and "Unresolved" in output
    assert "Edit nothing" in charter and "lead's conclusions" in charter


def assert_design_contract(design):
    card = section(design, "**Card review**", "**Story**")
    for claim in DESIGN_CLAIMS:
        assert claim in card, f"card-review design no longer states: {claim}"


def test_card_reviewer_is_shipped_and_routed_before_slots_are_spent():
    agents = {path.stem for path in (PLUGIN / "agents").glob("*.md")}
    assert "card-reviewer" in agents
    assert_open_route(SKILL.read_text(), PROCESS.read_text())


def test_route_isolation_guard_reds_when_shipped_instructions_are_removed():
    skill = SKILL.read_text()
    process = PROCESS.read_text()
    assert_open_route(skill, process)
    with pytest.raises((AssertionError, IndexError, ValueError)):
        assert_open_route(section(skill, "1. **", "2. **"), process)
    for fragment in ("card-reviewer", "author's conclusions", "work.py note"):
        line = next(line for line in skill.splitlines() if fragment in line)
        with pytest.raises((AssertionError, IndexError, ValueError)):
            assert_open_route(skill.replace(line + "\n", ""), process)
    # token, not line: dropping the line takes the `1. **Card review**` heading with
    # it, so `section` raises before any route assertion is reached and the mutation
    # proves only that the heading exists
    for token in ("`/sprint-close`", "corrected slate"):
        with pytest.raises(AssertionError):
            assert_open_route(skill, process.replace(token, "the lead", 1))


def test_charter_contract_and_its_fault_injections():
    charter = CHARTER.read_text()
    assert_charter_contract(charter)
    checks = section(charter, "## Checks", "## Output")
    for label in numbered_items(checks):
        item = re.search(
            rf"^\d+\. \*\*{re.escape(label)}\*\*.*?(?=^\d+\. \*\*|\Z)",
            checks,
            re.M | re.S,
        ).group()
        with pytest.raises(AssertionError):
            assert_charter_contract(charter.replace(item, ""))
    for fragment in ("lead's conclusions", "falsified premise", "## Slate — RED|GREEN"):
        line = next(line for line in charter.splitlines() if fragment in line)
        with pytest.raises(AssertionError):
            assert_charter_contract(charter.replace(line + "\n", ""))


def test_design_pins_timing_harness_evidence_and_residuals():
    design = DESIGN.read_text()
    assert_design_contract(design)
    card = section(design, "**Card review**", "**Story**")
    for claim in DESIGN_CLAIMS:
        with pytest.raises(AssertionError):
            assert_design_contract(design.replace(card, card.replace(claim, "omitted decision")))
