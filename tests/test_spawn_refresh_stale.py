"""A ready card's declared paths stay current until its story is spawned."""

import json
import subprocess
from pathlib import Path

import pytest
from close_free_card_cases import add_free_card, checkout_free, commit_on_free
from close_helpers import close, free, free_repo, worktree_land_setup
from slate_review_helpers import card_refresh, receipt_of, refresh_repo, stub_card_refresher
from spawn_helpers import seed_refresh_receipt, spawn, stub_claude

TARGET = """\n#### story-157 — follow predecessor   [planned]
Context: demo.
Files: src/thing.py
AC:
- Given a current path, When spawned, Then work starts
Verify: true
Executor: claude/sonnet/medium
"""


def git(repo, env, *args):
    result = subprocess.run(["git", *args], cwd=repo, env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def predecessor_and_target(tmp_path):
    repo, env, _g, predecessor, _branch = worktree_land_setup(tmp_path)
    plan = Path(env["XP_DATA"]) / "plan.md"
    plan.write_text(plan.read_text() + TARGET)
    seed_refresh_receipt(repo, env, "story-157")
    assert spawn(repo, env, "ready", "story-157").returncode == 0
    receipt = json.loads(receipt_of(env, "story-157").read_text())
    before = git(repo, env, "rev-parse", "main")
    landed = close(predecessor, env, "land")
    assert landed.returncode == 0, landed.stderr
    assert git(repo, env, "rev-parse", "main") != before
    assert git(repo, env, "show", "main:src/thing.py") == "A = 2"
    state = git(repo, env, "log", "-1", "--format=%H", "--", "src/thing.py")
    assert receipt["files"]["src/thing.py"] != state
    return repo, env, plan


def test_a_predecessor_land_moving_a_declared_path_refuses_before_worktree(tmp_path):
    repo, env, _plan = predecessor_and_target(tmp_path)
    stub_claude(tmp_path)

    refused = spawn(repo, env, "story-157")

    assert refused.returncode == 2, refused.stdout + refused.stderr
    assert "src/thing.py changed since story-157's card refresh" in refused.stderr
    assert "--refresh" in refused.stderr
    assert "spawn.py story-157" in refused.stderr
    assert "spawn.py amend story-157" in refused.stderr
    assert "spawn.py ready story-157" not in refused.stderr
    assert not (tmp_path / "launch.json").exists()
    assert not (Path(env["XP_DATA"]) / "handoffs/story-157.json").exists()
    assert not git(repo, env, "branch", "--list", "*story-157*")


def test_an_undeclared_commit_does_not_stale_the_receipt(tmp_path):
    repo, env, _plan = predecessor_and_target(tmp_path)
    seed_refresh_receipt(repo, env, "story-157")
    (repo / "unrelated.txt").write_text("new base state\n")
    git(repo, env, "add", "unrelated.txt")
    git(repo, env, "commit", "-qm", "change undeclared path")
    stub_claude(tmp_path)

    launched = spawn(repo, env, "story-157")

    assert launched.returncode == 0, launched.stderr
    assert (tmp_path / "launch.json").exists()


def test_an_amended_card_can_spawn_with_the_original_path_receipt(tmp_path):
    repo, env, plan = predecessor_and_target(tmp_path)
    seed_refresh_receipt(repo, env, "story-157")
    current = "#### story-157 — follow predecessor   [ready]\nContext: demo."
    plan.write_text(plan.read_text().replace(current, current.replace("demo.", "clarified.")))
    assert "Context: clarified." in plan.read_text()
    amended = spawn(repo, env, "amend", "story-157", "--reason", "clarified claim")
    assert amended.returncode == 0, amended.stderr
    receipt = json.loads(receipt_of(env, "story-157").read_text())
    marker = Path(env["XP_DATA"]) / "markers/story-157.ready.json"
    assert json.loads(marker.read_text())["digest"] != receipt["digest"]
    stub_claude(tmp_path)

    launched = spawn(repo, env, "story-157")

    assert launched.returncode == 0, launched.stderr
    assert (tmp_path / "launch.json").exists()


def test_refresh_after_a_move_recovers_an_unchanged_ready_card(tmp_path):
    repo, env, _plan = predecessor_and_target(tmp_path)
    stub_card_refresher(tmp_path, findings="no card change\n")

    refreshed = card_refresh(repo, env, "story-157")

    assert refreshed.returncode == 0, refreshed.stderr
    receipt = json.loads(receipt_of(env, "story-157").read_text())
    state = git(repo, env, "log", "-1", "--format=%H", "--", "src/thing.py")
    assert receipt["files"]["src/thing.py"] == state
    assert "spawn.py story-157" in refreshed.stdout
    assert "spawn.py amend story-157" not in refreshed.stdout
    assert "spawn.py ready story-157" not in refreshed.stdout
    stub_claude(tmp_path)
    assert spawn(repo, env, "story-157").returncode == 0


def test_a_free_card_spawns_without_a_refresh_receipt(tmp_path):
    repo, env, g = free_repo(tmp_path)
    assert free(repo, env, "fix-typo", "start").returncode == 0
    _branch, key = checkout_free(g)
    commit_on_free(repo, g)
    add_free_card(env, key)
    git(repo, env, "checkout", "-q", "main")
    assert spawn(repo, env, "ready", key).returncode == 0
    assert not receipt_of(env, key).exists()
    stub_claude(tmp_path)

    executor = "/".join(("claude", "sonnet", "medium"))
    launched = spawn(repo, env, key, executor)

    assert launched.returncode == 0, launched.stderr
    assert (tmp_path / "launch.json").exists()


def test_resume_skips_a_receipt_staled_after_the_first_spawn(tmp_path):
    repo, env, _plan = predecessor_and_target(tmp_path)
    seed_refresh_receipt(repo, env, "story-157")
    stub_claude(tmp_path)
    assert spawn(repo, env, "story-157").returncode == 0
    (repo / "src/thing.py").write_text("A = 3\n")
    git(repo, env, "add", "src/thing.py")
    git(repo, env, "commit", "-qm", "move declared path after spawn")

    resumed = spawn(repo, env, "resume", "story-157")

    assert resumed.returncode == 0, resumed.stderr
    assert "changed since" not in resumed.stderr


def test_land_uses_drift_without_a_receipt_check(tmp_path):
    repo, env, _g, predecessor, _branch = worktree_land_setup(tmp_path)
    seed_refresh_receipt(repo, env)
    receipt = json.loads(receipt_of(env).read_text())
    story_state = git(predecessor, env, "log", "-1", "--format=%H", "--", "src/thing.py")
    assert receipt["files"]["src/thing.py"] != story_state

    landed = close(predecessor, env, "land")

    assert landed.returncode == 0, landed.stderr
    assert git(repo, env, "show", "main:src/thing.py") == "A = 2"


def test_a_changed_ready_refresh_requires_amend_then_spawn(tmp_path):
    repo, env, plan = predecessor_and_target(tmp_path)
    stub_card_refresher(tmp_path, correction="Context: corrected after predecessor landed.")

    refreshed = card_refresh(repo, env, "story-157")

    assert refreshed.returncode == 0, refreshed.stderr
    assert "spawn.py amend story-157" in refreshed.stdout
    assert "spawn.py ready story-157" not in refreshed.stdout
    assert "Context: corrected" in plan.read_text()
    stub_claude(tmp_path)
    drifted = spawn(repo, env, "story-157")
    assert drifted.returncode == 2 and "edited after its plan review" in drifted.stderr
    amended = spawn(repo, env, "amend", "story-157", "--reason", "corrected claim")
    assert amended.returncode == 0, amended.stderr
    assert spawn(repo, env, "story-157").returncode == 0


@pytest.mark.parametrize(
    "knobs",
    [
        {"unparsable": True},
        {"correction": "Context: corrected.", "direct_plan": True},
        {"correction": "Context: corrected.", "skip_apply": True},
        {"findings": ""},
    ],
)
def test_ready_refresh_failure_names_the_ready_card_recovery(tmp_path, knobs):
    repo, env, _g, _plan = refresh_repo(tmp_path)
    seed_refresh_receipt(repo, env)
    assert spawn(repo, env, "ready", "story-042").returncode == 0
    (repo / "src/thing.py").parent.mkdir(exist_ok=True)
    (repo / "src/thing.py").write_text("A = 2\n")
    git(repo, env, "add", "src/thing.py")
    git(repo, env, "commit", "-qm", "move declared path")
    stub_card_refresher(tmp_path, **knobs)

    refused = card_refresh(repo, env)

    assert refused.returncode == 2
    assert "spawn.py story-042" in refused.stderr
    assert "spawn.py amend story-042" in refused.stderr
    assert "spawn.py ready story-042" not in refused.stderr


def test_amend_receipt_refusal_names_ready_card_recovery(tmp_path):
    repo, env, _plan = predecessor_and_target(tmp_path)

    refused = spawn(repo, env, "amend", "story-157", "--reason", "new claim")

    assert refused.returncode == 2
    assert "src/thing.py changed since" in refused.stderr
    assert "spawn.py story-157" in refused.stderr
    assert "spawn.py amend story-157" in refused.stderr
    assert "spawn.py ready story-157" not in refused.stderr


def test_current_ready_receipt_refusal_names_spawn_or_amend(tmp_path):
    repo, env, _g, _plan = refresh_repo(tmp_path)
    seed_refresh_receipt(repo, env)
    assert spawn(repo, env, "ready", "story-042").returncode == 0

    refused = card_refresh(repo, env)

    assert refused.returncode == 2
    assert "the receipt is current" in refused.stderr
    assert "spawn.py story-042" in refused.stderr
    assert "spawn.py amend story-042" in refused.stderr
    assert "spawn.py ready story-042" not in refused.stderr


def test_ready_receipt_remint_names_amend_then_spawn(tmp_path):
    repo, env, _g, plan = refresh_repo(tmp_path)
    seed_refresh_receipt(repo, env)
    assert spawn(repo, env, "ready", "story-042").returncode == 0
    plan.write_text(plan.read_text().replace("Context: demo.", "Context: updated claim."))

    reminted = card_refresh(repo, env)

    assert reminted.returncode == 0, reminted.stderr
    assert "re-minted locally" in reminted.stdout
    assert "spawn.py amend story-042" in reminted.stdout
    assert "spawn.py story-042" in reminted.stdout
    assert "spawn.py ready story-042" not in reminted.stdout
    assert spawn(repo, env, "amend", "story-042", "--reason", "updated claim").returncode == 0
