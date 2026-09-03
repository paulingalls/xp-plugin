"""The sprint slate reaches an independent reader before any story slot is spent."""

import ast
import json
import re
import runpy
import subprocess
import sys
from pathlib import Path

import pytest
from spawn_helpers import make_repo

ROOT = Path(__file__).parent.parent
PLUGIN = ROOT / "plugins" / "xp-plugin"
CHARTER = PLUGIN / "agents" / "slate-reviewer.md"
CREATE_SKILL = PLUGIN / "skills" / "create-sprint" / "SKILL.md"
CLOSE_SKILL = PLUGIN / "skills" / "sprint-close" / "SKILL.md"
PROCESS = PLUGIN / "PROCESS.md"
DESIGN = ROOT / "docs" / "DESIGN.md"
PLAN_TEMPLATE = PLUGIN / "templates" / "plan.md"
SLATE_REVIEW = PLUGIN / "scripts" / "slate_review.py"
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


def assert_open_route(create_skill, close_skill, process):
    opening = section(create_skill, "## Open", "## Done")
    card_step = section(process, "1. **Slate review**", "2. **Story**")
    assert opening.index("slate-reviewer") < opening.index("close.py sprint <id> start")
    assert opening.index("slate_review.py") < opening.index("close.py sprint <id> start")
    assert "full proposed slate" in opening and "`sprint_cap`" in opening
    assert "author's conclusions" in opening and "do not give" in opening
    assert "corrected cards" in opening and "work.py note" in opening
    assert "`/create-sprint`" in card_step and "`/sprint-close`" not in card_step
    assert "corrected slate" in card_step
    assert card_step.index("`/create-sprint`") < card_step.index("spawn.py ready")
    for fragment in ("slate-reviewer", "slate_review.py", "git switch", "Open the sprint"):
        assert fragment not in close_skill


def slate_repo(tmp_path):
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


def stub_slate_reviewer(tmp_path, findings="## story-042 — GREEN\n\n## Slate — GREEN\n", slate=""):
    binary = tmp_path / "bin" / "claude"
    binary.parent.mkdir(exist_ok=True)
    launch = tmp_path / "slate-launch.json"
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


def slate_review(repo, env, sprint_id="1"):
    return subprocess.run(
        [sys.executable, str(SLATE_REVIEW), sprint_id],
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


def assert_one_lifecycle(slate_source, plan_source, review_source):
    shared = lifecycle_shapes(slate_source)
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
    card = section(design, "**Slate review**", "**Story**")
    for claim in DESIGN_CLAIMS:
        assert claim in card, f"card-review design no longer states: {claim}"


def shipped_sources():
    return {p: p.read_text() for p in sorted(PLUGIN.rglob("*")) if p.suffix in {".md", ".py"}}


def assert_review_vocabulary(sources, design, template):
    normalized = {path: " ".join(text.lower().split()) for path, text in sources.items()}
    old = [path.relative_to(PLUGIN) for path, text in normalized.items() if "card review" in text]
    assert not old, f"old sprint-step name survives in {old}"
    rule = "every review is named for the artifact it reads"
    owners = [(path, text) for path, text in normalized.items() if rule in text]
    assert len(owners) == 1, f"review naming rule has {len(owners)} shipped owners"
    rule_path, owner = owners[0]
    # The rule SENTENCE, not the whole owner: the loop restates three of the four names at
    # their action sites, so `owner.index` read a restatement as the declaration.
    rule_line = owner.split(rule, 1)[1].split(".", 1)[0]
    names = ("slate review", "card refresh", "execution plan review", "diff review")
    positions = [rule_line.index(name) for name in names]
    assert positions == sorted(positions), "review artifacts are not named in process order"
    assert "reserved **card refresh**" in rule_line
    for name in ("slate review", "execution plan review", "diff review"):
        # Outside the declaring file: a name only PROCESS repeats reaches no artifact a
        # lead opens, and counting every file greened `diff review` at zero such uses.
        uses = sum(t.count(name) for p, t in normalized.items() if p != rule_path)
        assert uses, f"{name} is declared but names no shipped review"

    migration = next(ln for ln in design.splitlines() if ln.startswith("**Review-name migration ("))
    for token in (
        "2026-09-02",
        "Sprint 17",
        "`card review` named the sprint-slate step",
        "`execution plan` named the per-clone roadmap",
        "`card-review-incomplete`",
        "`card-reviews/`",
        "PROCESS.md owns the current naming rule",
    ):
        assert token in migration, f"review-name migration no longer states {token}"
    assert template.startswith("# Roadmap\n")
    assert "plan.md                        roadmap:" in design


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
    assert findings.is_absolute() and findings.is_file()
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
    unreserved = dict(sources)
    unreserved[rule_path] = unreserved[rule_path].replace("reserved ", "", 1)
    with pytest.raises(AssertionError):
        assert_review_vocabulary(unreserved, design, template)
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
