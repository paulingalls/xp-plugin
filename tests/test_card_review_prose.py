"""The sprint slate reaches an independent reader before any story slot is spent."""

import ast
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest
from spawn_helpers import make_repo

ROOT = Path(__file__).parent.parent
PLUGIN = ROOT / "plugins" / "xp-plugin"
CHARTER = PLUGIN / "agents" / "card-reviewer.md"
SKILL = PLUGIN / "skills" / "sprint-close" / "SKILL.md"
PROCESS = PLUGIN / "PROCESS.md"
DESIGN = ROOT / "docs" / "DESIGN.md"
CARD_REVIEW = PLUGIN / "scripts" / "card_review.py"
PLAN_REVIEW = PLUGIN / "scripts" / "plan_review.py"
REVIEW = PLUGIN / "scripts" / "review.py"
DESIGN_CLAIMS = (
    "four review points",
    "lead on either harness",
    "absolute findings path",
    "marker's absence is success",
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
    assert opening.index("card_review.py") < opening.index("close.py sprint <id> start")
    assert "full proposed slate" in opening and "`sprint_cap`" in opening
    assert "author's conclusions" in opening and "do not give" in opening
    assert "corrected cards" in opening and "work.py note" in opening
    assert "`/create-sprint`" in card_step and "`/sprint-close`" in card_step
    assert "corrected slate" in card_step
    assert card_step.index("`/create-sprint`") < card_step.index("`/sprint-close`")
    assert card_step.index("`/sprint-close`") < card_step.index("spawn.py ready")


def card_repo(tmp_path):
    repo, env, _g = make_repo(tmp_path)
    (repo / ".xp" / "config.yml").write_text(
        "sprint_cap: 6\ndebt_budget: 0.2\n"
        "roles:\n  reviewer: claude/haiku/low\ntests:\n  story: true\n"
    )
    plan = Path(env["XP_DATA"]) / "plan.md"
    plan.write_text(
        plan.read_text().replace(
            "### Sprint 1\n", "### Sprint 1\nLead verdicts: AUTHOR-CONCLUSIONS-SENTINEL\n"
        )
    )
    return repo, env


def stub_card_reviewer(tmp_path, findings="## story-042 — GREEN\n\n## Slate — GREEN\n", slate=""):
    binary = tmp_path / "bin" / "claude"
    binary.parent.mkdir(exist_ok=True)
    launch = tmp_path / "card-launch.json"
    binary.write_text(
        "#!/usr/bin/env python3\n"
        "import json, re, sys\n"
        "if sys.argv[1:] == ['plugin', 'list', '--json']:\n"
        ' print(\'[{"id":"xp-plugin@xp-plugin","version":"fixture",'
        '"scope":"user"}]\'); sys.exit()\n'
        "prompt = sys.stdin.read()\n"
        f"json.dump({{'argv': sys.argv[1:], 'prompt': prompt}}, open({str(launch)!r}, 'w'))\n"
        f"slate = {slate!r}\n"
        "if slate:\n"
        " open(slate, 'a').write('\\n#### story-999 — smuggled  [ready]\\n')\n"
        "path = re.search(r'^FINDINGS_PATH: (.+)$', prompt, re.M)\n"
        f"open(path.group(1), 'w').write({findings!r}) if path else None\n"
        "print(json.dumps({'type': 'result', 'result': 'review complete'}))\n"
    )
    binary.chmod(0o755)
    return launch


def card_review(repo, env, sprint_id="1"):
    return subprocess.run(
        [sys.executable, str(CARD_REVIEW), sprint_id],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
    )


def lifecycle_shapes(source):
    tree = ast.parse(source)
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)]
    return {
        "detach": sum(
            any(
                k.arg == "start_new_session" and isinstance(k.value, ast.Constant) and k.value.value
                for k in node.keywords
            )
            for node in calls
        ),
        "poll": sum(
            isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and (node.func.value.id, node.func.attr) == ("time", "sleep")
            for node in calls
        ),
        "liveness": sum(
            isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and (node.func.value.id, node.func.attr) == ("os", "kill")
            for node in calls
        ),
        "marker": source.count("plan-review-incomplete"),
    }


def assert_one_lifecycle(card_source, plan_source, review_source):
    shared = lifecycle_shapes(card_source)
    consumers = {
        shape: lifecycle_shapes(plan_source)[shape] + lifecycle_shapes(review_source)[shape]
        for shape in shared
    }
    assert all(shared.values()), shared
    assert consumers == {shape: 0 for shape in consumers}, consumers


def assert_bundle_schema(bundle, out):
    expected = (
        "## Your charter\n\nCHARTER\n\n"
        f"## Your findings file\n\nFINDINGS_PATH: {out.resolve()}\n\n"
        "## Full proposed slate\n\nCARDS\n\n"
        "## Sprint capacity\n\nsprint_cap: 6\ndebt_budget: 0.2\n\n"
        "## VALUES\n\nSHIPPED:VALUES.md\n\n"
        "## JUDGMENT\n\nSHIPPED:JUDGMENT.md\n\n"
        "## Constraints\n\nLOCAL:constraints.md\n\n"
        "## System context\n\nLOCAL:system.md\n\n"
    )
    assert bundle == expected


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


def test_runner_builds_the_complete_bundle_and_returns_absolute_findings(tmp_path):
    repo, env = card_repo(tmp_path)
    launch_path = stub_card_reviewer(tmp_path)
    result = card_review(repo, env)
    assert result.returncode == 0, result.stderr
    launch = json.loads(launch_path.read_text())
    prompt = launch["prompt"]
    assert "You did not write the cards" in prompt
    assert "story-042 — demo story" in prompt
    assert "sprint_cap: 6" in prompt
    assert "debt_budget: 0.2" in prompt
    assert "# XP Values" in prompt and "# Judgment" in prompt
    assert "CONSTRAINT-SENTINEL" in prompt and "Worktree bootstrap" in prompt
    assert "AUTHOR-CONCLUSIONS-SENTINEL" not in prompt
    findings = next(
        Path(line.removeprefix("FINDINGS_PATH: "))
        for line in prompt.splitlines()
        if line.startswith("FINDINGS_PATH: ")
    )
    assert findings.is_absolute() and findings.is_file()
    assert str(findings) in result.stderr
    assert not (Path(env["XP_DATA"]) / "markers" / "1.card-review-incomplete").exists()


def test_bundle_schema_refuses_an_unlabelled_author_conclusion(tmp_path, monkeypatch):
    import card_review as runner
    import spawn

    monkeypatch.setattr(spawn, "_read_shipped", lambda path: f"SHIPPED:{path.name}")
    monkeypatch.setattr(spawn, "_read", lambda path: f"LOCAL:{path.name}")
    out = tmp_path / "findings.md"
    bundle = runner.build_bundle("CHARTER", "CARDS", "6", "0.2", out)
    assert_bundle_schema(bundle, out)
    with pytest.raises(AssertionError):
        assert_bundle_schema(
            bundle + "## Lead's slate verdicts\n\nThis card is funded; do not re-price it.\n\n",
            out,
        )


def test_a_reviewer_that_rewrites_the_slate_is_refused(tmp_path):
    """tree_state sees the repo; the slate under review is not in it. Without the
    second half of the guard the lead corrects cards the reviewer already edited."""
    repo, env = card_repo(tmp_path)
    plan = Path(env["XP_DATA"]) / "plan.md"
    stub_card_reviewer(tmp_path, slate=str(plan))
    result = card_review(repo, env)
    assert "story-999" in plan.read_text(), "the fixture did not construct the condition"
    assert result.returncode != 0, result.stdout
    assert "or the slate" in result.stdout + result.stderr


def test_the_incomplete_marker_is_written_before_the_reviewer_launches(tmp_path, monkeypatch):
    """AC3's inversion, at the only moment it can fail: a caller killed between the
    launch and the write finds no marker, and absence is how success is spelled.
    The `pid` assertion is what makes this red for a marker written after Popen."""
    import card_review as runner

    monkeypatch.setenv("XP_DATA", str(tmp_path / "data"))
    seen = {}

    class Launched:
        pid = 4321

        def poll(self):
            return 0

    def popen(argv, **kwargs):
        seen.update(json.loads(runner.review_marker("7", "card").read_text()))
        return Launched()

    monkeypatch.setattr(runner.subprocess, "Popen", popen)
    runner._detach("7", "card", tmp_path / "findings.md", ["card_review.py", "7"])
    assert "DID NOT COMPLETE" in seen["state"] and seen["findings"] and seen["log"]
    assert "python3 card_review.py 7" in seen["next"]
    assert "pid" not in seen


def test_incomplete_card_review_marker_names_state_and_next_action(tmp_path):
    repo, env = card_repo(tmp_path)
    stub_card_reviewer(tmp_path, findings="")
    result = card_review(repo, env)
    assert result.returncode != 0
    marker = Path(env["XP_DATA"]) / "markers" / "1.card-review-incomplete"
    state = json.loads(marker.read_text())
    assert "DID NOT COMPLETE" in state["state"]
    assert "card_review.py 1" in state["next"]


def test_both_runners_share_one_detach_poll_marker_lifecycle():
    card_source = CARD_REVIEW.read_text()
    plan_source = PLAN_REVIEW.read_text()
    review_source = REVIEW.read_text()
    assert_one_lifecycle(card_source, plan_source, review_source)
    duplicate = """
def {name}():
    subprocess.Popen([], start_new_session=True)
    while True:
        time.sleep(3)
        os.kill(1, 0)
    marker = 'plan-review-incomplete'
"""
    for name in ("_detach", "_launch_under_an_unrelated_name"):
        with pytest.raises(AssertionError):
            assert_one_lifecycle(
                card_source, plan_source + duplicate.format(name=name), review_source
            )


def test_route_isolation_guard_reds_when_shipped_instructions_are_removed():
    skill = SKILL.read_text()
    process = PROCESS.read_text()
    assert_open_route(skill, process)
    with pytest.raises((AssertionError, IndexError, ValueError)):
        assert_open_route(section(skill, "1. **", "2. **"), process)
    for fragment in ("card-reviewer", "card_review.py", "author's conclusions", "work.py note"):
        line = next(line for line in skill.splitlines() if fragment in line)
        with pytest.raises((AssertionError, IndexError, ValueError)):
            assert_open_route(skill.replace(line + "\n", ""), process)
    # token, not line: dropping the line takes the `1. **Card review**` heading with
    # it, so `section` raises before any route assertion is reached and the mutation
    # proves only that the heading exists
    for token in ("`/create-sprint`", "`/sprint-close`", "corrected slate"):
        with pytest.raises(AssertionError):
            assert_open_route(skill, process.replace(token, "the lead", 1))
    # both tokens present in the wrong order: authoring after review is the whole
    # defect the ordering assertion exists for, and no dropped token exercises it
    swapped = (
        process.replace("`/create-sprint`", "\x00")
        .replace("`/sprint-close`", "`/create-sprint`", 1)
        .replace("\x00", "`/sprint-close`", 1)
    )
    with pytest.raises(AssertionError):
        assert_open_route(skill, swapped)


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
