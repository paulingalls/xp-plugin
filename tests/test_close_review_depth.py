import json
import re
from pathlib import Path

import pytest
from close_helpers import PLUGIN, close, launches, make_repo, mint_ready, ready_marker
from handoff import draft_path


def review_with_depths(tmp_path, card_depth, draft, unreadable=None):
    repo, env, _g = make_repo(tmp_path, status="planned")
    plan = Path(env["XP_DATA"]) / "plan.md"
    if card_depth:
        plan.write_text(plan.read_text().replace("Verify: true", f"Verify: true\n{card_depth}"))
    mint_ready(repo, env)
    drafted = draft_path(Path(env["XP_DATA"]), "story-042")
    drafted.parent.mkdir(parents=True, exist_ok=True)
    if unreadable == "directory":
        drafted.mkdir()
    elif unreadable == "bytes":
        drafted.write_bytes(b"\xff\xfe")
    elif isinstance(draft, str):
        drafted.write_text(f"# story-042 execution plan\n\n{draft}\n")
    before_plan = plan.read_bytes()
    before_marker = ready_marker(tmp_path).read_bytes()
    before_digest = json.loads(before_marker)["digest"]

    result = close(repo, env, "review")

    assert result.returncode == 0, result.stderr
    assert plan.read_bytes() == before_plan
    assert ready_marker(tmp_path).read_bytes() == before_marker
    assert json.loads(ready_marker(tmp_path).read_bytes())["digest"] == before_digest
    return launches(tmp_path)[0]["stdin"]


def find_depth_section(prompt):
    match = re.search(r"^## Close-review depth\n\n(.*?)(?=^## |\Z)", prompt, re.M | re.S)
    return match.group(1) if match else None


def depth_section(prompt):
    match = find_depth_section(prompt)
    assert match, "review prompt has no Close-review depth section"
    return match


def test_plan_review_can_raise_card_standard_to_deep(tmp_path):
    prompt = review_with_depths(
        tmp_path,
        "Close review: standard — card assignment",
        "Close review: deep. Assigned after plan review",
    )
    depth = depth_section(prompt).lower()
    assert re.search(r"^close review:\s*deep\b", depth, re.M) and "effective depth" in depth
    assert re.search(r"plan review[^.]*assign[^.]*deep", depth)


def test_card_deep_is_not_lowered_by_plan_review_standard(tmp_path):
    prompt = review_with_depths(
        tmp_path,
        "Close review: deep — card assignment",
        "Close review: standard. Assigned after plan review",
    )
    depth = depth_section(prompt).lower()
    assert re.search(r"^close review:\s*deep\b", depth, re.M) and "effective depth" in depth
    assert "card" in depth
    assert re.search(r"plan review[^.]*standard", depth)
    assert "lower" in depth


def test_single_file_without_a_draft_uses_only_the_card_depth(tmp_path):
    prompt = review_with_depths(tmp_path, "Close review: standard", None)
    depth = depth_section(prompt).lower()
    assert re.search(r"^close review:\s*standard\b", depth, re.M) and "effective depth" in depth
    assert "card" in depth
    assert not re.search(r"plan review[^.]*assign", depth)
    assert "unreadable" not in depth


def test_no_declared_depth_adds_no_depth_section(tmp_path):
    prompt = review_with_depths(tmp_path, None, "Reason: no depth was assigned")
    assert find_depth_section(prompt) is None


@pytest.mark.parametrize("unreadable", ["directory", "bytes"])
def test_unreadable_plan_review_depth_fails_safe_to_deep(tmp_path, unreadable):
    prompt = review_with_depths(tmp_path, "Close review: standard", None, unreadable=unreadable)
    depth = depth_section(prompt).lower()
    assert re.search(r"^close review:\s*deep\b", depth, re.M) and "effective depth" in depth
    assert re.search(r"plan review[^.]*unreadable", depth)


def test_story_reviewer_charter_points_to_the_depth_section():
    paragraphs = (PLUGIN / "agents" / "story-reviewer.md").read_text().split("\n\n")
    (paragraph,) = [p for p in paragraphs if "Close-review depth" in p]
    assert len(re.findall(r"[.!?](?:\s|$)", paragraph)) == 1
    assert "deep" in paragraph and "standard" in paragraph
