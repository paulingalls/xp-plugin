"""The optional preflight command runs outside all receipt and record paths."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "plugins/xp-plugin/scripts/close"))

from close_free_card_cases import add_free_card, checkout_free, commit_on_free, spawn_free
from close_helpers import close, free, free_repo, marker_file, stub_reviewer
from close_helpers import make_repo as story_repo
from sprint_helpers import make_repo as sprint_repo
from sprint_helpers import marker_path, record_reviews, sprint, work


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


def test_runner_refuses_when_later_chained_command_fails(capfd):
    import preflight

    raw, commands, error = preflight.prepare(f"true && {sys.executable} -c 'exit(7)'")
    assert not error
    assert "exit code 7" in preflight.run(raw, commands)
    assert "preflight:" not in capfd.readouterr().out


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
    assert preflight.run("", []) == ""
    assert capfd.readouterr().out == ""


def _set_preflight(repo, g, command):
    config = repo / ".xp/config.yml"
    config.write_text(f"preflight: {command}\n" + config.read_text())
    assert g("add", ".xp/config.yml").returncode == 0
    assert g("commit", "-qm", "configure preflight").returncode == 0


def _sentinel_gate(repo, g, tier, sentinel):
    config = repo / ".xp/config.yml"
    text = config.read_text()
    assert f"  {tier}: true\n" in text
    config.write_text(text.replace(f"  {tier}: true\n", f"  {tier}: touch {sentinel}\n", 1))
    assert g("commit", "-qam", "gate writes a sentinel").returncode == 0


def _steps(result):
    return [line for line in result.stdout.splitlines() if line.startswith("would run")]


def _script(repo, g, exit_code):
    script = repo / "check-env"
    script.write_text(
        f'#!/bin/sh\necho preflight-output\n[ "${{XP_TEST_PREPARE:-}}" = 1 ] && exit 0\n'
        f"exit {exit_code}\n"
    )
    script.chmod(0o755)
    assert g("add", "check-env").returncode == 0
    assert g("commit", "-qm", "add environment check").returncode == 0


def _mutating_script(repo, g, tracked):
    script = repo / "check-env"
    script.write_text(
        '#!/bin/sh\n[ "${XP_TEST_PREPARE:-}" = 1 ] && exit 0\n'
        f"printf 'preflight edit\\n' >> {tracked}\n"
    )
    script.chmod(0o755)
    assert g("add", "check-env").returncode == 0
    assert g("commit", "-qm", "add mutating environment check").returncode == 0


def test_story_land_refuses_preflight_tree_change_before_gates(tmp_path):
    repo, env, g = story_repo(tmp_path, files="src/thing.py, .xp/config.yml")
    _mutating_script(repo, g, "src/thing.py")
    _set_preflight(repo, g, "./check-env")
    _sentinel_gate(repo, g, "story", tmp_path / "gate-ran")
    stub_reviewer(tmp_path)
    assert close(repo, env | {"XP_TEST_PREPARE": "1"}, "review").returncode == 0
    marker = marker_file(tmp_path)
    before = marker.read_bytes()
    result = close(repo, env, "land")
    assert result.returncode == 2, result.stdout + result.stderr
    assert "preflight" in result.stderr and "dirty" in result.stderr
    assert "src/thing.py" in g("status", "--short").stdout
    assert marker.read_bytes() == before
    assert not (tmp_path / "data/markers/story-042.land-red.json").exists()
    assert not (tmp_path / "gate-ran").exists()


def test_sprint_land_refuses_preflight_tree_change_before_gates(tmp_path):
    repo, env, g = sprint_repo(tmp_path)
    _mutating_script(repo, g, "src.py")
    _set_preflight(repo, g, "./check-env")
    _sentinel_gate(repo, g, "full", tmp_path / "gate-ran")
    record_reviews(tmp_path, repo, env)
    marker = marker_path(tmp_path)
    before = marker.read_bytes()
    result = sprint(repo, env, "land")
    assert result.returncode == 2, result.stdout + result.stderr
    assert "preflight" in result.stderr and "dirty" in result.stderr
    assert "src.py" in g("status", "--short").stdout
    assert marker.read_bytes() == before
    assert not (tmp_path / "gate-ran").exists()


@pytest.mark.parametrize("dry_run", [False, True])
def test_story_land_red_or_preview_keeps_records(tmp_path, dry_run):
    repo, env, g = story_repo(tmp_path, files="src/thing.py, .xp/config.yml")
    _script(repo, g, 7)
    _set_preflight(repo, g, "./check-env")
    _sentinel_gate(repo, g, "story", tmp_path / "gate-ran")
    stub_reviewer(tmp_path)
    assert close(repo, env | {"XP_TEST_PREPARE": "1"}, "review").returncode == 0
    marker = marker_file(tmp_path)
    before = marker.read_bytes()
    plan = tmp_path / "data/plan.md"
    plan_before = plan.read_bytes()
    result = close(repo, env, "land", *(["--dry-run"] if dry_run else []))
    if dry_run:
        assert result.returncode == 0, result.stderr
        assert _steps(result)[0] == "would run preflight: ./check-env"
        assert "preflight-output" not in result.stdout
    else:
        assert result.returncode == 2, result.stderr
        assert "preflight-output" in result.stdout
        assert result.stderr.splitlines()[-1].startswith("refused: preflight")
        assert "nothing was recorded" in result.stderr
    assert marker.read_bytes() == before
    assert plan.read_bytes() == plan_before
    assert not (tmp_path / "data/markers/story-042.land-red.json").exists()
    assert not (tmp_path / "gate-ran").exists()


def test_sprint_land_red_keeps_receipt(tmp_path):
    repo, env, g = sprint_repo(tmp_path)
    _script(repo, g, 7)
    _set_preflight(repo, g, "./check-env")
    _sentinel_gate(repo, g, "full", tmp_path / "gate-ran")
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
    assert not (tmp_path / "gate-ran").exists()


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
    sentinel = tmp_path / "falsifier-ran"
    filed = work(
        repo, env, "debt", "--claim", "c", "--falsifier", f"touch {sentinel}", "--files", "a.py"
    )
    assert filed.returncode == 0, filed.stderr
    sentinel.unlink(missing_ok=True)
    plan, ledger = tmp_path / "data/plan.md", tmp_path / "data/work.md"
    before, ledger_before = plan.read_bytes(), ledger.read_bytes()
    result = sprint(repo, env, "start", *(["--dry-run"] if dry_run else []))
    if dry_run:
        assert result.returncode == 0, result.stderr
        assert result.stdout.splitlines()[0].startswith("dry run:")
        assert _steps(result)[0] == "would run preflight: ./check-env"
        assert "preflight-output" not in result.stdout
    else:
        assert result.returncode == 2, result.stderr
        assert "preflight-output" in result.stdout
        assert "nothing was recorded" in result.stderr.splitlines()[-1]
    assert plan.read_bytes() == before
    assert ledger.read_bytes() == ledger_before
    assert not sentinel.exists()
    assert not marker_path(tmp_path).exists()


def test_sprint_start_refuses_preflight_tree_change_before_batch(tmp_path):
    repo, env, g = sprint_repo(tmp_path)
    _mutating_script(repo, g, "src.py")
    _set_preflight(repo, g, "./check-env")
    sentinel = tmp_path / "falsifier-ran"
    filed = work(
        repo, env, "debt", "--claim", "c", "--falsifier", f"touch {sentinel}", "--files", "a.py"
    )
    assert filed.returncode == 0, filed.stderr
    sentinel.unlink(missing_ok=True)
    ledger = tmp_path / "data/work.md"
    ledger_before = ledger.read_bytes()
    result = sprint(repo, env, "start")
    assert result.returncode == 2, result.stdout + result.stderr
    assert "preflight left the working tree dirty" in result.stderr
    assert "src.py" in g("status", "--short").stdout
    assert ledger.read_bytes() == ledger_before
    assert not sentinel.exists()


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
    _sentinel_gate(repo, g, "story", tmp_path / "gate-ran")
    assert g("push", "-q", "origin", "main").returncode == 0
    assert free(repo, env, "fix-typo", "start").returncode == 0
    branch, key = checkout_free(g)
    commit_on_free(repo, g)
    add_free_card(env, key)
    env["XP_TEST_PREPARE"] = "1"
    tree = spawn_free(repo, env, g, tmp_path, key)
    assert g("worktree", "remove", "--force", str(tree)).returncode == 0
    assert g("checkout", "-q", branch).returncode == 0
    assert free(repo, env, "fix-typo", "review").returncode == 0
    env.pop("XP_TEST_PREPARE")
    (tmp_path / "gate-ran").unlink(missing_ok=True)
    preview = free(repo, env, "fix-typo", "land", "--dry-run")
    assert preview.returncode == 0, preview.stderr
    assert _steps(preview)[0] == "would run preflight: ./check-env"
    assert "preflight-output" not in preview.stdout
    result = free(repo, env, "fix-typo", "land")
    assert result.returncode == 2, result.stderr
    assert "preflight-output" in result.stdout
    assert "nothing was recorded" in result.stderr.splitlines()[-1]
    assert not (tmp_path / "gate-ran").exists()


@pytest.mark.parametrize("dry_run", [False, True])
def test_malformed_review_and_sprint_land_refuse_dry_and_real(tmp_path, dry_run):
    flag = ["--dry-run"] if dry_run else []
    repo, env, g = story_repo(tmp_path / "story", files="src/thing.py, .xp/config.yml")
    _sentinel_gate(repo, g, "story", tmp_path / "gate-ran")
    stub_reviewer(tmp_path / "story")
    _set_preflight(repo, g, "echo nope | cat")
    story = close(repo, env, "review", *flag)
    repo, env, g = sprint_repo(tmp_path / "sprint")
    _set_preflight(repo, g, "echo nope | cat")
    _sentinel_gate(repo, g, "full", tmp_path / "gate-ran")
    record_reviews(tmp_path / "sprint", repo, env)
    for result in (story, sprint(repo, env, "land", *flag)):
        assert result.returncode == 2, result.stdout
        assert result.stderr.splitlines()[-1].startswith("refused: preflight")
    assert not (tmp_path / "gate-ran").exists()
