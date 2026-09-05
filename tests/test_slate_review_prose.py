"""The sprint slate reaches an independent reader before any story slot is spent.

Pure parsing/assertion helpers live in slate_review_helpers.py (extracted at
story-103, constraint 8): this file keeps every collected test.
"""

import json
import re
import runpy
import subprocess
from pathlib import Path

import pytest
from slate_review_helpers import (
    CHARTER,
    CLOSE_SKILL,
    CREATE_SKILL,
    DESIGN,
    DESIGN_CLAIMS,
    PLAN_REVIEW,
    PLAN_TEMPLATE,
    PLUGIN,
    PROCESS,
    REVIEW,
    SLATE_REVIEW,
    assert_bundle_schema,
    assert_charter_contract,
    assert_design_contract,
    assert_one_lifecycle,
    assert_open_route,
    assert_review_vocabulary,
    numbered_items,
    section,
    shipped_sources,
    slate_repo,
    slate_review,
    stub_slate_reviewer,
)


def git_out(repo, env, *args):
    return subprocess.run(
        ["git", *args], cwd=repo, env=env, capture_output=True, text=True
    ).stdout.strip()


def test_slate_reviewer_is_shipped_and_routed_before_slots_are_spent():
    agents = {path.stem for path in (PLUGIN / "agents").glob("*.md")}
    assert "slate-reviewer" in agents
    assert_open_route(CREATE_SKILL.read_text(), CLOSE_SKILL.read_text(), PROCESS.read_text())


def test_runner_builds_the_complete_bundle_and_returns_absolute_findings(tmp_path):
    repo, env = slate_repo(tmp_path)
    launch_path = stub_slate_reviewer(tmp_path)
    result = slate_review(repo, env)
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
    assert findings.is_absolute() and findings.name == "sprint-1.round-1.md"
    assert findings.is_file()
    assert str(findings) in result.stderr
    assert not (Path(env["XP_DATA"]) / "markers" / "1.slate-review-incomplete").exists()


def test_bundle_schema_refuses_an_unlabelled_author_conclusion(tmp_path, monkeypatch):
    import slate_review as runner
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
    repo, env = slate_repo(tmp_path)
    plan = Path(env["XP_DATA"]) / "plan.md"
    stub_slate_reviewer(tmp_path, slate=str(plan))
    result = slate_review(repo, env)
    assert "story-999" in plan.read_text(), "the fixture did not construct the condition"
    assert result.returncode != 0, result.stdout
    assert "or the slate" in result.stdout + result.stderr


def test_the_incomplete_marker_is_written_before_the_reviewer_launches(tmp_path, monkeypatch):
    """AC3's inversion, at the only moment it can fail: a caller killed between the
    launch and the write finds no marker, and absence is how success is spelled.
    The `pid` assertion is what makes this red for a marker written after Popen."""
    import slate_review as runner

    monkeypatch.setenv("XP_DATA", str(tmp_path / "data"))
    seen = {}

    class Launched:
        pid = 4321

        def poll(self):
            return 0

    def popen(argv, **kwargs):
        seen.update(json.loads(runner.review_marker("7", "slate").read_text()))
        return Launched()

    monkeypatch.setattr(runner.subprocess, "Popen", popen)
    runner._detach("7", "slate", tmp_path / "findings.md", ["slate_review.py", "7"])
    assert "DID NOT COMPLETE" in seen["state"] and seen["findings"] and seen["log"]
    assert "python3 slate_review.py 7" in seen["next"]
    assert "pid" not in seen


def test_incomplete_slate_review_marker_names_state_and_next_action(tmp_path):
    repo, env = slate_repo(tmp_path)
    stub_slate_reviewer(tmp_path, findings="")
    result = slate_review(repo, env)
    assert result.returncode != 0
    marker = Path(env["XP_DATA"]) / "markers" / "1.slate-review-incomplete"
    state = json.loads(marker.read_text())
    assert "DID NOT COMPLETE" in state["state"]
    assert "slate_review.py 1" in state["next"]


def test_both_runners_share_one_detach_poll_marker_lifecycle():
    slate_source = SLATE_REVIEW.read_text()
    plan_source = PLAN_REVIEW.read_text()
    review_source = REVIEW.read_text()
    assert_one_lifecycle(slate_source, plan_source, review_source)
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
                slate_source, plan_source + duplicate.format(name=name), review_source
            )


def test_route_isolation_guard_reds_when_shipped_instructions_are_removed():
    create_skill = CREATE_SKILL.read_text()
    close_skill = CLOSE_SKILL.read_text()
    process = PROCESS.read_text()
    assert_open_route(create_skill, close_skill, process)
    opening = section(create_skill, "## Open", "## Done")
    with pytest.raises((AssertionError, IndexError, ValueError)):
        assert_open_route(create_skill.replace(opening, ""), close_skill, process)
    for fragment in ("slate-reviewer", "slate_review.py", "author's conclusions", "work.py note"):
        line = next(line for line in create_skill.splitlines() if fragment in line)
        with pytest.raises((AssertionError, IndexError, ValueError)):
            assert_open_route(create_skill.replace(line + "\n", ""), close_skill, process)
    for token in ("`/create-sprint`", "corrected slate"):
        with pytest.raises(AssertionError):
            assert_open_route(create_skill, close_skill, process.replace(token, "the lead", 1))
    # both tokens present in the wrong order: ready before authoring is the whole defect
    # the ordering assertion exists for, and no dropped token exercises it
    step = section(process, "1. **Slate review**", "2. **Story**")
    flip = step.replace("`/create-sprint`", "\x00").replace("spawn.py ready", "`/create-sprint`", 1)
    with pytest.raises(AssertionError):
        flipped = flip.replace("\x00", "spawn.py ready", 1)
        assert_open_route(create_skill, close_skill, process.replace(step, flipped))
    with pytest.raises(AssertionError):
        assert_open_route(create_skill, close_skill + opening, process)
    with pytest.raises(AssertionError):
        assert_open_route(
            create_skill, close_skill, process.replace("fresh reader", "`/sprint-close`")
        )


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
    card = section(design, "**Slate review**", "**Story**")
    for claim in DESIGN_CLAIMS:
        with pytest.raises(AssertionError):
            assert_design_contract(design.replace(card, card.replace(claim, "omitted decision")))


def test_review_vocabulary_has_one_shipped_owner_and_a_dated_migration():
    sources = shipped_sources()
    design = DESIGN.read_text()
    template = PLAN_TEMPLATE.read_text()
    assert_review_vocabulary(sources, design, template)

    rule = "every review is named for the artifact it reads"
    rule_path = next(p for p, t in sources.items() if rule in t.lower())
    mutated = dict(sources)
    mutated[rule_path] = mutated[rule_path].replace("slate review", "card review", 1)
    with pytest.raises(AssertionError):
        assert_review_vocabulary(mutated, design, template)
    for token in (
        "every review is named for the artifact it reads",
        "card refresh",
        "execution plan review",
        "diff review",
    ):
        changed = dict(sources)
        changed[rule_path], count = re.subn(
            re.escape(token), "omitted name", changed[rule_path], count=1, flags=re.I
        )
        assert count == 1, f"fault did not remove {token}"
        with pytest.raises((AssertionError, ValueError)):
            assert_review_vocabulary(changed, design, template)
    # the binding stripped from every file BUT the declaring one: dropping the owner's
    # own restatement instead let `uses` pass at zero real uses
    unbound = {
        p: t if p == rule_path else re.sub("diff review", "spawned", t, flags=re.I)
        for p, t in sources.items()
    }
    with pytest.raises(AssertionError, match="names no shipped review"):
        assert_review_vocabulary(unbound, design, template)
    # both names present, order destroyed: no removal exercises the ordering claim
    order = "**execution plan review** → **diff review**"
    swapped = dict(sources)
    swapped[rule_path] = swapped[rule_path].replace(
        order, " → ".join(reversed(order.split(" → "))), 1
    )
    with pytest.raises(AssertionError, match="process order"):
        assert_review_vocabulary(swapped, design, template)
    migration = next(ln for ln in design.splitlines() if ln.startswith("**Review-name migration ("))
    for token in (
        "2026-09-02",
        "`card review` named the sprint-slate step",
        "`execution plan` named the per-clone roadmap",
    ):
        with pytest.raises((AssertionError, StopIteration)):
            assert_review_vocabulary(
                sources, design.replace(migration, migration.replace(token, "")), template
            )
    with pytest.raises(AssertionError):
        assert_review_vocabulary(sources, design, template.replace("# Roadmap", "# Execution Plan"))
    config = PLUGIN / "templates" / "config.yml"
    changed = dict(sources)
    changed[config] = changed[config].replace("lead:", "lead: # card review over the slate", 1)
    with pytest.raises(AssertionError):
        assert_review_vocabulary(changed, design, template)


def test_a_zero_padded_sprint_id_names_the_marker_the_hook_reads(tmp_path, monkeypatch):
    """The seam story-091's runner and story-084's hook share, found by the sprint
    review because neither story's own review could see the other side of it.
    slate_review.py names the marker from the id the LEAD TYPED; session_start.py
    reads `### Sprint (\\d+)` through int(). So `07` writes 07.card-review-incomplete
    and the hook looks for 7.slate-review-incomplete — and an incomplete slate review
    is then spelled exactly like a completed one, which is the inversion AC3 rests
    on: absence of the marker is the success signal.

    Asserted against session_start's OWN derivation, not against a second call to
    this function: self-equality is satisfied by any normalisation the runner
    shares with itself, and `zfill(3)` is one — measured, it made both spellings
    `007.card-review-incomplete` and left this test green with the hook still
    reading `7.`. The end-to-end half is in tests/test_session_recover.py."""
    monkeypatch.setenv("XP_DATA", str(tmp_path))
    module = runpy.run_path(str(PLUGIN / "scripts" / "slate_review.py"))
    import session_start

    sprint, _sections = session_start.sprint_sections("### Sprint 07\n#### s — d   [planned]\n")
    padded = module["review_marker"]("07", "slate")

    assert padded.name == f"{int(sprint)}.slate-review-incomplete", f"{padded.name} unread"


def test_a_story_id_is_never_renumbered(tmp_path, monkeypatch):
    """The other side of the same fix: a plan review's identifier is a story id,
    not a number, and must survive verbatim."""
    monkeypatch.setenv("XP_DATA", str(tmp_path))
    module = runpy.run_path(str(PLUGIN / "scripts" / "slate_review.py"))

    assert module["review_marker"]("story-042", "plan").name.startswith("story-042.")
