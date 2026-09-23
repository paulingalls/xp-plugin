"""The lead's open-only route never enters sprint close checks."""

import shlex
import subprocess
import sys
from pathlib import Path

import pytest
from sprint_helpers import PLAN, make_repo, sprint

OPEN = Path(__file__).parent.parent / "plugins/xp-plugin/scripts/open_sprint.py"


def invoke(repo, env, *args, cwd=None):
    return subprocess.run(
        [sys.executable, str(OPEN), *args],
        cwd=cwd or repo,
        env=env,
        capture_output=True,
        text=True,
    )


def fixture(tmp_path, *, terminal=False, retired=False, recorded=""):
    plan = PLAN.replace("[in-progress]", "[planned]", 1)
    if not terminal:
        plan = plan.replace("also done   [done]", "also done   [ready]")
    if retired:
        plan = plan.replace("also done   [done]", "also done   [retired]")
    repo, env, g = make_repo(tmp_path, plan=plan)
    branch = tmp_path / "data/sprint_branch"
    if recorded:
        branch.write_text(recorded + "\n")
    else:
        branch.unlink()
    return repo, env, g, branch


def hook(repo, tmp_path):
    output = tmp_path / "hook-event"
    script = tmp_path / "hook.py"
    script.write_text(
        f"import pathlib, sys\npathlib.Path({str(output)!r}).write_text(' '.join(sys.argv[1:]))\n"
    )
    config = repo / ".xp/config.yml"
    config.write_text(
        f"lifecycle_command: {shlex.join([sys.executable, str(script)])}\n" + config.read_text()
    )
    return output


def falsifier(tmp_path):
    output = tmp_path / "close-batch"
    script = tmp_path / "falsifier.py"
    script.write_text(f"import pathlib; pathlib.Path({str(output)!r}).write_text('ran')\n")
    (tmp_path / "data/work.md").write_text(
        "## debt 2026-01-01T00:00:00Z\nClaim: sentinel\n"
        f"Falsifier: `{shlex.join([sys.executable, str(script)])}`\n"
        "Files: src.py\n\n"
    )
    return output


def test_open_from_subdirectory_records_branch_and_runs_hook(tmp_path):
    repo, env, _g, branch = fixture(tmp_path)
    output = hook(repo, tmp_path)
    nested = repo / "nested"
    nested.mkdir()

    result = invoke(repo, env, "2", cwd=nested)

    assert result.returncode == 0, result.stderr
    assert branch.read_text() == "sprint-002\n"
    assert output.read_text() == "sprint-open 2"
    assert "## Milestone 1   [in-progress]" in (tmp_path / "data/plan.md").read_text()
    other = tmp_path / "other"
    other.mkdir()
    old_repo, old_env, _g, old_branch = fixture(other)
    assert sprint(old_repo, old_env, "start").returncode == 0
    assert old_branch.read_bytes() == branch.read_bytes()


@pytest.mark.parametrize(
    ("recorded", "terminal", "retired", "message", "names_close"),
    [
        ("", True, False, "nothing to open", True),
        ("", True, True, "nothing to open", True),
        ("sprint-002", True, False, "already open", True),
        ("sprint-002", False, False, "already open", False),
        ("sprint-003", False, False, "records sprint-003, not sprint-002", False),
    ],
)
@pytest.mark.parametrize("dry", [(), ("--dry-run",)])
def test_distinct_open_states(tmp_path, recorded, terminal, retired, message, names_close, dry):
    repo, env, _g, branch = fixture(tmp_path, terminal=terminal, retired=retired, recorded=recorded)
    output = hook(repo, tmp_path)
    batch = falsifier(tmp_path)
    before = (tmp_path / "data/plan.md").read_bytes()

    result = invoke(repo, env, "2", *dry)

    assert result.returncode == 2, result.stderr
    assert message in result.stderr
    assert ("/sprint-close" in result.stderr) == names_close
    assert not output.exists()
    assert not batch.exists()
    assert (tmp_path / "data/plan.md").read_bytes() == before
    if recorded:
        assert branch.read_text().strip() == recorded
    else:
        assert not branch.exists()


@pytest.mark.parametrize("branch_name", ["main", "sprint-2"])
def test_wrong_branch_refuses_before_hook(tmp_path, branch_name):
    repo, env, g, branch = fixture(tmp_path)
    output = hook(repo, tmp_path)
    g("checkout", "-q", branch_name) if branch_name == "main" else g("branch", "-m", branch_name)

    result = invoke(repo, env, "2")

    assert result.returncode == 2
    assert "refused: open" in result.stderr
    assert not output.exists() and not branch.exists()


def test_dry_run_is_read_only(tmp_path):
    repo, env, _g, branch = fixture(tmp_path)
    output = hook(repo, tmp_path)
    before = (tmp_path / "data/plan.md").read_bytes()

    result = invoke(repo, env, "2", "--dry-run")

    assert result.returncode == 0, result.stderr
    assert "dry run" in result.stdout
    assert not output.exists() and not branch.exists()
    assert (tmp_path / "data/plan.md").read_bytes() == before


def test_role_and_git_guards_and_help(tmp_path):
    repo, env, _g, branch = fixture(tmp_path)
    output = hook(repo, tmp_path)

    role = invoke(repo, env | {"XP_ROLE": "executor"}, "2")
    outside = invoke(repo, env, "2", cwd=tmp_path)
    help_result = invoke(repo, env | {"XP_ROLE": "executor"}, "--help", cwd=tmp_path)

    assert role.returncode == 2 and "only the lead" in role.stderr
    assert outside.returncode == 2 and "not inside a git repository" in outside.stderr
    assert help_result.returncode == 0 and "--dry-run" in help_result.stdout
    assert not branch.exists() and not output.exists()
