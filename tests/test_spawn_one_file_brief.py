"""Executor authority follows the current declaration and its accepted review."""

import json
import subprocess
import sys
from pathlib import Path

import pytest
from spawn_helpers import SPAWN, make_repo, spawn
from test_card_update_contract import edited_stages
from test_spawn_stages import stub_stages


def how(prompt):
    return prompt.split("## How you work\n\n", 1)[1].split("\n## Your story card", 1)[0]


def assert_authority(prompt, multifile, root):
    brief = how(prompt).lower()
    plan = str(root / "plans/story-042.plan.md").lower()
    if multifile:
        assert "re-read the reviewed plan" in brief
        assert plan in brief
    else:
        assert "no execution plan by design" in brief
        assert "card is the authority" in brief
        assert "re-read" not in brief
        assert plan not in prompt.lower()
        assert "Predecessor plan draft" not in prompt
        assert "plan draft is missing" not in prompt.lower()
    assert "story close, review, and land belong to the lead" in brief
    assert "executor hands back after the green commit" in brief


@pytest.mark.parametrize(
    "files,multifile",
    [
        ("src/thing.py", False),
        ("src/thing.py, src/other.py", True),
    ],
)
def test_dry_run_brief_uses_card_authority(tmp_path, files, multifile):
    repo, env, _g = make_repo(tmp_path, files=files)
    stub_stages(tmp_path)
    result = spawn(repo, env, "story-042", "--dry-run")
    assert result.returncode == 0, result.stderr
    assert_authority(result.stdout, multifile, Path(env["XP_DATA"]))


@pytest.mark.parametrize("change_to_one", [False, True])
def test_replan_rebuild_uses_current_card_shape(tmp_path, change_to_one):
    repo, env, _g = make_repo(tmp_path, files="src/thing.py, src/other.py")
    events = stub_stages(tmp_path, blocking_diff=True)
    first = spawn(repo, env, "story-042")
    assert first.returncode != 0 and events.exists(), first.stdout + first.stderr
    plan = Path(env["XP_DATA"]) / "plan.md"
    amended = plan.read_text().replace("Then Z", "Then AMENDED")
    if change_to_one:
        amended = amended.replace("src/thing.py, src/other.py", "src/thing.py")
    plan.write_text(amended)
    assert spawn(repo, env, "amend", "story-042", "--reason", "authority changed").returncode == 0
    before = len(events.read_text().splitlines())
    corrected = "Then REVIEWED_AFTER_REPLAN"
    edited_stages(tmp_path, [("Then AMENDED", corrected)], blocking_diff=True)
    program = f"""
import sys
sys.path.insert(0, {str(SPAWN.parent)!r})
import spawn
sys.argv = ["spawn.py", "resume", "story-042"]
raise SystemExit(spawn.main())
"""
    resumed_run = subprocess.run(
        [sys.executable, "-c", program],
        cwd=repo,
        env=dict(env, XP_SPAWN_TEST="1"),
        capture_output=True,
        text=True,
    )
    assert resumed_run.returncode != 0
    resumed = [json.loads(line) for line in events.read_text().splitlines()[before:]]
    prompt = next(e["prompt"] for e in resumed if e["role"] == "teammate")
    assert corrected in prompt
    assert corrected in plan.read_text()
    assert "Predecessor handback" in prompt
    assert_authority(prompt, True, Path(env["XP_DATA"]))


def test_multi_file_respawn_without_replan_inherits_the_reviewed_plan(tmp_path):
    repo, env, _g = make_repo(tmp_path, files="src/thing.py, src/other.py")
    events = stub_stages(tmp_path, blocking_diff=True)
    assert spawn(repo, env, "story-042").returncode != 0
    before = len(events.read_text().splitlines())
    spawn(repo, env, "resume", "story-042")
    resumed = [json.loads(line) for line in events.read_text().splitlines()[before:]]
    assert [e["role"] for e in resumed][:1] == ["teammate"], "the resume replanned"
    draft = Path(env["XP_DATA"]) / "plans/story-042.plan.md"
    assert f"Predecessor plan draft\n\n{draft.resolve()}" in resumed[0]["prompt"]
