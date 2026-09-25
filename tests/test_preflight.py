"""The optional preflight command runs outside all receipt and record paths."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "plugins/xp-plugin/scripts/close"))

from close_free_card_cases import add_free_card, checkout_free, commit_on_free, spawn_free
from close_helpers import close, free, free_repo, marker_file, stub_reviewer
from close_helpers import make_repo as story_repo
from sprint_helpers import make_repo as sprint_repo
from sprint_helpers import marker_path, record_reviews, sprint


def test_runner_refuses_red_without_recording(tmp_path, capfd, monkeypatch):
    import preflight

    monkeypatch.chdir(tmp_path)
    command = f"{sys.executable} -c \"print('preflight-output'); exit(7)\""
    raw, commands, error = preflight.prepare(command)
    assert not error
    red = preflight.run(raw, commands)
    out = capfd.readouterr().out
    assert "preflight-output" in out
    assert red.startswith("refused: preflight")
    assert "exit code 7" in red
    assert "nothing was recorded" in red


def test_runner_validates_chains_and_warns_only_above_60(monkeypatch, capfd):
    import preflight

    raw, commands, error = preflight.prepare("true && true")
    assert not error and len(commands) == 2
    times = iter((0, 60, 0, 61))
    monkeypatch.setattr(preflight.time, "monotonic", lambda: next(times))
    assert not preflight.run(raw, commands)
    assert "warning" not in capfd.readouterr().out
    assert not preflight.run(raw, commands)
    assert "warning: preflight exceeded 60s" in capfd.readouterr().out
    for bad in ("echo nope | cat", "definitely-not-on-path"):
        assert "preflight" in preflight.prepare(bad)[2]
    assert preflight.prepare("") == ("", [], "")


def _set_preflight(repo, g, command):
    config = repo / ".xp/config.yml"
    config.write_text(f"preflight: {command}\n" + config.read_text())
    assert g("add", ".xp/config.yml").returncode == 0
    assert g("commit", "-qm", "configure preflight").returncode == 0


def _script(repo, g, exit_code):
    script = repo / "check-env"
    script.write_text(f"#!/bin/sh\necho preflight-output\nexit {exit_code}\n")
    script.chmod(0o755)
    assert g("add", "check-env").returncode == 0
    assert g("commit", "-qm", "add environment check").returncode == 0


@pytest.mark.parametrize("dry_run", [False, True])
def test_story_land_red_or_preview_keeps_records(tmp_path, dry_run):
    repo, env, g = story_repo(tmp_path, files="src/thing.py, .xp/config.yml")
    _script(repo, g, 7)
    _set_preflight(repo, g, "./check-env")
    stub_reviewer(tmp_path)
    assert close(repo, env, "review").returncode == 0
    marker = marker_file(tmp_path)
    before = marker.read_bytes()
    plan = tmp_path / "data/plan.md"
    plan_before = plan.read_bytes()
    result = close(repo, env, "land", *(["--dry-run"] if dry_run else []))
    if dry_run:
        assert result.returncode == 0, result.stderr
        assert "would run preflight: ./check-env" in result.stdout
        assert "preflight-output" not in result.stdout
    else:
        assert result.returncode == 2, result.stderr
        assert "preflight-output" in result.stdout
        assert result.stderr.splitlines()[-1].startswith("refused: preflight")
        assert "nothing was recorded" in result.stderr
    assert marker.read_bytes() == before
    assert plan.read_bytes() == plan_before
    assert not (tmp_path / "data/markers/story-042.land-red.json").exists()


def test_sprint_land_red_keeps_receipt(tmp_path):
    repo, env, g = sprint_repo(tmp_path)
    _script(repo, g, 7)
    _set_preflight(repo, g, "./check-env")
    record_reviews(tmp_path, repo, env)
    marker = marker_path(tmp_path)
    before = marker.read_bytes()
    plan = tmp_path / "data/plan.md"
    plan_before = plan.read_bytes()
    result = sprint(repo, env, "land")
    assert result.returncode == 2, result.stderr
    assert "preflight-output" in result.stdout
    assert "nothing was recorded" in result.stderr.splitlines()[-1]
    assert marker.read_bytes() == before
    assert plan.read_bytes() == plan_before


def test_sprint_land_rechecks_preflight_with_a_green_receipt(tmp_path):
    repo, env, g = sprint_repo(tmp_path)
    script = repo / "check-env"
    script.write_text('#!/bin/sh\necho preflight-output\nexit "${XP_PREFLIGHT_EXIT:-0}"\n')
    script.chmod(0o755)
    assert g("add", "check-env").returncode == 0
    assert g("commit", "-qm", "add environment check").returncode == 0
    _set_preflight(repo, g, "./check-env")
    record_reviews(tmp_path, repo, env)
    first = sprint(repo, env, "land")
    assert "preflight: " in first.stdout, first.stdout + first.stderr
    marker = marker_path(tmp_path)
    state = marker.read_bytes()
    assert '"full_tier"' in state.decode()
    second = sprint(repo, env | {"XP_PREFLIGHT_EXIT": "7"}, "land")
    assert second.returncode == 2
    assert "preflight-output" in second.stdout
    assert "nothing was recorded" in second.stderr.splitlines()[-1]
    assert "reused" not in second.stdout
    assert marker.read_bytes() == state


@pytest.mark.parametrize("dry_run", [False, True])
def test_sprint_start_red_or_preview_keeps_records(tmp_path, dry_run):
    repo, env, g = sprint_repo(tmp_path)
    _script(repo, g, 7)
    _set_preflight(repo, g, "./check-env")
    plan = tmp_path / "data/plan.md"
    before = plan.read_bytes()
    result = sprint(repo, env, "start", *(["--dry-run"] if dry_run else []))
    if dry_run:
        assert result.returncode == 0, result.stderr
        assert result.stdout.splitlines()[0].startswith("dry run:")
        assert "would run preflight: ./check-env" in result.stdout
        assert "preflight-output" not in result.stdout
    else:
        assert result.returncode == 2, result.stderr
        assert "preflight-output" in result.stdout
        assert "nothing was recorded" in result.stderr.splitlines()[-1]
    assert plan.read_bytes() == before
    assert not marker_path(tmp_path).exists()


@pytest.mark.parametrize("command", ["echo nope | cat", "definitely-not-on-path"])
def test_malformed_start_refuses_dry_and_real(tmp_path, command):
    repo, env, g = sprint_repo(tmp_path)
    _set_preflight(repo, g, command)
    for args in (("start", "--dry-run"), ("start",)):
        result = sprint(repo, env, *args)
        assert result.returncode == 2
        assert "preflight" in result.stderr


def test_sprint_land_preview_validates_without_running(tmp_path):
    repo, env, g = sprint_repo(tmp_path)
    _script(repo, g, 7)
    _set_preflight(repo, g, "./check-env")
    record_reviews(tmp_path, repo, env)
    preview = sprint(repo, env, "land", "--dry-run")
    assert preview.returncode == 0, preview.stderr
    assert preview.stdout.splitlines()[0] == "would run preflight: ./check-env"
    assert "preflight-output" not in preview.stdout


def test_unfinished_start_skips_malformed_preflight(tmp_path):
    from sprint_helpers import PLAN

    plan = PLAN.replace("done thing   [done]", "done thing   [ready]")
    repo, env, g = sprint_repo(tmp_path, plan=plan)
    _set_preflight(repo, g, "echo nope | cat")
    result = sprint(repo, env, "start")
    assert "preflight" not in result.stdout + result.stderr


def test_free_land_runs_preflight_before_gates(tmp_path):
    repo, env, g = free_repo(tmp_path)
    _script(repo, g, 7)
    _set_preflight(repo, g, "./check-env")
    assert g("push", "-q", "origin", "main").returncode == 0
    assert free(repo, env, "fix-typo", "start").returncode == 0
    branch, key = checkout_free(g)
    commit_on_free(repo, g)
    add_free_card(env, key)
    tree = spawn_free(repo, env, g, tmp_path, key)
    assert g("worktree", "remove", "--force", str(tree)).returncode == 0
    assert g("checkout", "-q", branch).returncode == 0
    assert free(repo, env, "fix-typo", "review").returncode == 0
    result = free(repo, env, "fix-typo", "land")
    assert result.returncode == 2, result.stderr
    assert "preflight-output" in result.stdout
    assert "nothing was recorded" in result.stderr.splitlines()[-1]
