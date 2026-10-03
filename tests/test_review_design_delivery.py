"""Installed bundle transport; these fixtures make no claim about reviewer judgment."""

import json
import re
import shutil
import subprocess
import sys

import pytest
from close_helpers import PLUGIN, close, launches, make_repo
from diff_reference_helpers import read_named_diff
from slate_review_helpers import slate_repo, stub_slate_reviewer
from sprint_helpers import make_repo as sprint_repo
from sprint_helpers import section, sprint, stage_key, staged_stub
from test_plan_review import TestTheLaunch as PlanFixture
from test_plan_review import plan_review, stub_planner


def installed(tmp_path):
    plugin = tmp_path / "installed" / "xp-plugin" / "0.32.1"
    shutil.copytree(PLUGIN, plugin)
    judgment = plugin / "JUDGMENT.md"
    judgment.write_text(judgment.read_text() + "\nInstallation-specific judgment payload.\n")
    return plugin


def body(plugin, role):
    text = (plugin / "agents" / f"{role}.md").read_text()
    return text.split("---", 2)[2].strip()


def stage_body(plugin, stage):
    text = body(plugin, "sprint-reviewer")
    preamble = text[: text.index("\n## finder")].strip()
    match = re.search(rf"^## {stage}\n.*?(?=^## |\Z)", text, re.M | re.S)
    return preamble + "\n\n" + match.group().strip()


def delivered_section(bundle, title, until):
    assert f"## {title}\n\n" in bundle, f"missing region: {title}"
    assert f"## {until}\n\n" in bundle, f"missing boundary: {until}"
    return section(bundle, title, until)


def assert_delivery(bundle, plugin, charter, next_title="Your report"):
    delivered = delivered_section(bundle, "Your charter", next_title).strip()
    assert delivered.split("## Checks", 1)[-1] == charter.split("## Checks", 1)[-1]
    following = (
        "Shipped card template"
        if next_title == "Your findings file" and "## Full proposed slate" in bundle
        else ("VALUES" if next_title == "Your report" else "Constraints")
    )
    assert (
        delivered_section(bundle, "JUDGMENT", following).strip()
        == (plugin / "JUDGMENT.md").read_text().strip()
    )


def mutate(plugin, path, before, after):
    target = plugin / path
    text = target.read_text()
    assert before in text
    target.write_text(text.replace(before, after, 1))


def transport_fault(plugin, surface, fault):
    if fault == "intact":
        return
    if surface in ("plan", "slate"):
        path = f"scripts/{surface}_review.py"
        line = '("JUDGMENT", _read_shipped(PLUGIN_ROOT / "JUDGMENT.md")),'
        mutate(
            plugin, path, line, '("JUDGMENT", "stale shared rubric"),' if fault == "stale" else ""
        )
    elif fault == "expansion":
        mutate(
            plugin,
            "scripts/close/sprint_bundle.py",
            "*authority,",
            '*[(t, b) for t, b in authority if t != "JUDGMENT"],',
        )
    else:
        mutate(
            plugin,
            "scripts/close.py",
            '("JUDGMENT", Path(__file__).parent.parent / "JUDGMENT.md"),',
            "",
        )


def check_or_red(fault, check):
    if fault == "intact":
        check()
    else:
        with pytest.raises(AssertionError):
            check()


@pytest.mark.parametrize("fault", ["intact", "omit", "stale", "role"])
def test_shared_judgment_reaches_plan_and_slate(tmp_path, fault):
    for surface in ("plan", "slate"):
        root = tmp_path / surface
        root.mkdir()
        plugin = installed(root)
        expected = body(plugin, f"{surface}-reviewer")
        if fault == "role":
            mutate(
                plugin,
                f"scripts/{surface}_review.py",
                '("Your charter", charter),',
                '("Your charter", ""),',
            )
        else:
            transport_fault(plugin, surface, fault)
        if surface == "plan":
            repo, env, draft = PlanFixture().repo(root)
            rec = stub_planner(root)
            result = plan_review(
                repo, env, "story-042", str(draft), script=plugin / "scripts/plan_review.py"
            )
            bundle = json.loads(rec.read_text())["stdin"]
        else:
            repo, env = slate_repo(root)
            rec = stub_slate_reviewer(root)
            result = subprocess.run(
                [sys.executable, str(plugin / "scripts/slate_review.py"), "1"],
                cwd=repo,
                env=env,
                capture_output=True,
                text=True,
            )
            bundle = json.loads(rec.read_text())["prompt"]
        if fault != "role":
            assert result.returncode == 0, result.stderr
        check_or_red(
            fault,
            lambda bundle=bundle, plugin=plugin, expected=expected: assert_delivery(
                bundle, plugin, expected, "Your findings file"
            ),
        )


@pytest.mark.parametrize("fault", ["intact", "omit", "role"])
def test_shared_judgment_reaches_story(tmp_path, fault):
    repo, env, _g = make_repo(tmp_path)
    plugin = installed(tmp_path)
    expected = body(plugin, "story-reviewer")
    if fault == "role":
        mutate(
            plugin,
            "scripts/close.py",
            '("Your charter", review.charter()),',
            '("Your charter", ""),',
        )
    else:
        transport_fault(plugin, "story", fault)
    result = close(repo, env, "review", close=plugin / "scripts/close.py")
    assert result.returncode == 0, result.stderr
    captured = launches(tmp_path)
    assert len(captured) == 1
    check_or_red(fault, lambda: assert_delivery(captured[0]["stdin"], plugin, expected))


@pytest.mark.parametrize("fault", ["intact", "omit", "expansion", "stage", "angle"])
def test_shared_judgment_reaches_every_sprint_stage(tmp_path, fault):
    repo, env, _g = sprint_repo(tmp_path)
    plugin = installed(tmp_path)
    expected = {
        stage: stage_body(plugin, stage) for stage in ("finder", "verifier", "fixer", "closer")
    }
    angles = {p.stem: p.read_text().strip() for p in (plugin / "scripts/angles").glob("*.md")}
    if fault == "stage":
        mutate(
            plugin,
            "scripts/close/stages.py",
            'return found, ""\n\n\ndef check_roles',
            'found["closer"] = found["fixer"]\n    return found, ""\n\n\ndef check_roles',
        )
    elif fault == "angle":
        mutate(
            plugin,
            "scripts/close/stages.py",
            'return found, ""',
            'found[0] = (found[0][0], found[1][1])\n    return found, ""',
        )
    else:
        transport_fault(plugin, "sprint", fault)
    candidate = {
        "schema": 2,
        "fixed": [],
        "blocking": ["a constructed silent candidate"],
        "dropped": [],
        "debt": [],
    }
    staged_stub(tmp_path, find=candidate, verify=candidate)
    result = sprint(repo, env, "review", close=plugin / "scripts/close.py")
    assert result.returncode == 0, result.stderr
    captured = launches(tmp_path)
    keys = [stage_key(item["stdin"]) for item in captured]
    assert sorted(keys[:3]) == [f"find-{slug}" for slug in sorted(angles)]
    assert sorted(keys[3:-2]) == ["verify-1", "verify-2"]
    assert keys[-2:] == ["fix", "close"]

    def check():
        for item, key in zip(captured, keys, strict=True):
            bundle = item["stdin"]
            stage = (
                "finder"
                if key.startswith("find-")
                else (
                    "verifier"
                    if key.startswith("verify-")
                    else {"fix": "fixer", "close": "closer"}[key]
                )
            )
            assert_delivery(bundle, plugin, expected[stage])
            if stage == "finder":
                own = angles[key.removeprefix("find-")]
                assert (
                    delivered_section(bundle, "Your angle", "Findings from earlier rounds").strip()
                    == own
                )
                assert all(value not in bundle for value in angles.values() if value != own)

    check_or_red(fault, check)


@pytest.mark.parametrize("surface", ["story", "sprint"])
@pytest.mark.parametrize("fault", ["intact", "omit", "role"])
def test_shared_judgment_reaches_confirmation(tmp_path, surface, fault):
    repo, env, g = (make_repo if surface == "story" else sprint_repo)(tmp_path)
    plugin = installed(tmp_path)
    runner = close if surface == "story" else sprint
    assert runner(repo, env, "review", close=plugin / "scripts/close.py").returncode == 0
    first_count = len(launches(tmp_path))
    path = repo / ("src/thing.py" if surface == "story" else "src.py")
    path.write_text(path.read_text() + "LEAD_DELTA = 3\n")
    assert g("add", "-A").returncode == 0
    assert g("commit", "-qm", "lead implementation change").returncode == 0
    expected = body(plugin, "story-reviewer")
    if fault == "role":
        mutate(
            plugin,
            "scripts/review.py",
            'name: str = "story-reviewer"',
            'name: str = "plan-reviewer"',
        )
    else:
        transport_fault(plugin, surface, fault)
    result = runner(repo, env, "review", close=plugin / "scripts/close.py")
    assert result.returncode == 0, result.stderr
    captured = launches(tmp_path)[first_count:]
    assert len(captured) == 1
    title = "Cumulative diff" if surface == "story" else "The delta since the last recorded round"
    assert "+LEAD_DELTA = 3" in read_named_diff(captured[0]["stdin"], title, repo, env)
    if surface == "sprint":
        altitude = next(
            p for p in body(plugin, "sprint-reviewer").split("\n\n") if p.startswith("ALTITUDE")
        )
        assert (
            section(captured[0]["stdin"], "Sprint altitude", "Findings from earlier rounds").strip()
            == altitude
        )
    check_or_red(fault, lambda: assert_delivery(captured[0]["stdin"], plugin, expected))


@pytest.mark.parametrize("fault", ["intact", "omit", "stale", "cap"])
def test_shared_judgment_reaches_startup(tmp_path, fault):
    from test_session_start_profile import TestTheRealProfileAgainstTheRealCap

    fixture = TestTheRealProfileAgainstTheRealCap()
    plugin = fixture.copied_plugin(tmp_path, "startup", 521)
    expected = {name: (plugin / name).read_text() for name in ("JUDGMENT.md", "PROCESS.md")}
    rules = fixture.constraints_at_bytes(3_000)
    if fault == "omit":
        mutate(
            plugin,
            "scripts/session_start.py",
            '("JUDGMENT.md", safe(lambda: read(PLUGIN_ROOT / "JUDGMENT.md"))),',
            "",
        )
    elif fault == "stale":
        (plugin / "JUDGMENT.md").write_text("# Stale judgment\n")
    elif fault == "cap":
        target = plugin / "scripts/session_start.py"
        changed, count = re.subn(r"OUTPUT_CAP = \S+", "OUTPUT_CAP = 5_000", target.read_text())
        assert count == 1
        target.write_text(changed)
    output = fixture.run_constructed(tmp_path, "startup", plugin, rules)

    def check():
        for name, content in expected.items():
            assert content.strip() in output, f"incomplete startup region: {name}"
        assert rules in output, "incomplete startup constraints"

    check_or_red(fault, check)
