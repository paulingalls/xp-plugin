"""Pure parsing/assertion helpers for test_slate_review_prose.py, extracted at
story-103 to stay under constraint 8's 500-line cap while the card refresh
feature grows that file's collected tests."""

import ast
import re
import subprocess
import sys
from pathlib import Path

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
    "a receipt binds it to HEAD",
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
    assert "card refresh" in rule_line and "reserved" not in rule_line
    for name in ("slate review", "card refresh", "execution plan review", "diff review"):
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


SIBLING = """#### story-043 — the card refresh must not touch this one   [planned]
Context: untouched by story-042's refresh.
Files: src/other.py
AC:
- Given A, When B, Then C
Verify: true
"""


def refresh_repo(tmp_path):
    """A [planned] card with a SIBLING beside it, and no receipt: the two states
    `ready` must tell apart are "refreshed" and "never refreshed", so a fixture
    that inherits make_repo's mint would start past the guard under test."""
    repo, env, g = make_repo(tmp_path, status="planned")
    plan = Path(env["XP_DATA"]) / "plan.md"
    plan.write_text(plan.read_text() + SIBLING)
    return repo, env, g, plan


def stub_card_refresher(
    tmp_path, correction="", sibling=False, repo_file="", status="", findings="corrected 1 claim\n"
):
    """A fake `claude` standing in for the refresher, with one knob per motion the
    runner must refuse: `correction` edits its OWN card (the sanctioned edit),
    `sibling` a second card in the same plan, `repo_file` a path in the repo, and
    `status` the card's own lifecycle bracket."""
    binary = tmp_path / "bin" / "claude"
    binary.parent.mkdir(exist_ok=True)
    launch = tmp_path / "refresh-launch.json"
    binary.write_text(
        "#!/usr/bin/env python3\n"
        "import json, re, sys\n"
        "if sys.argv[1:] == ['plugin', 'list', '--json']:\n"
        ' print(\'[{"id":"xp-plugin@xp-plugin","version":"fixture",'
        '"scope":"user"}]\'); sys.exit()\n'
        "prompt = sys.stdin.read()\n"
        f"json.dump({{'argv': sys.argv[1:], 'prompt': prompt}}, open({str(launch)!r}, 'w'))\n"
        "plan = re.search(r'^PLAN_PATH: (.+)$', prompt, re.M).group(1)\n"
        "text = open(plan).read()\n"
        f"correction = {correction!r}\n"
        "if correction:\n"
        " text = text.replace('Context: demo.', correction, 1)\n"
        f"if {sibling!r}:\n"
        " text = text.replace('Context: untouched', 'Context: MEDDLED', 1)\n"
        f"if {status!r}:\n"
        f" text = text.replace('demo story   [planned]', 'demo story   [{status}]', 1)\n"
        "open(plan, 'w').write(text)\n"
        f"stray = {repo_file!r}\n"
        "open(stray, 'w').write('the refresher wrote here\\n') if stray else None\n"
        "path = re.search(r'^FINDINGS_PATH: (.+)$', prompt, re.M)\n"
        f"open(path.group(1), 'w').write({findings!r}) if path and {findings!r} else None\n"
        "print(json.dumps({'type': 'result', 'result': 'refresh complete'}))\n"
    )
    binary.chmod(0o755)
    return launch


def card_refresh(repo, env, story_id="story-042"):
    return subprocess.run(
        [sys.executable, str(SLATE_REVIEW), story_id, "--refresh"],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
    )


def receipt_of(env, story_id="story-042"):
    return Path(env["XP_DATA"]) / "card-refreshes" / f"{story_id}.json"
