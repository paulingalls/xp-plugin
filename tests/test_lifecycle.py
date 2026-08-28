"""Project-owned lifecycle writes at the three semantic close boundaries."""

import json
import shlex
import subprocess
import sys

from close import verify_commands
from close_helpers import CLOSE, free, free_repo, make_repo
from close_helpers import close as story


def recorder(tmp_path):
    script = tmp_path / "record.py"
    log = tmp_path / "lifecycle.jsonl"
    script.write_text(
        "import json, pathlib, subprocess, sys\n"
        "p = pathlib.Path(sys.argv[1])\n"
        "entry = {'argv': sys.argv[2:], 'main': subprocess.run(\n"
        "    ['git', 'rev-parse', 'main'], capture_output=True, text=True).stdout.strip()}\n"
        "with p.open('a') as f: f.write(json.dumps(entry) + '\\n')\n"
        "raise SystemExit(int(p.with_suffix('.exit').read_text()) "
        "if p.with_suffix('.exit').exists() else 0)\n"
    )
    return shlex.join([sys.executable, str(script), str(log), "fixed value"]), log


def entries(log):
    return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []


def run(command, event, identity):
    from lifecycle import run as lifecycle_run

    return lifecycle_run(command, event, identity)


def configure(repo, g, command, tier="true"):
    path = repo / ".xp" / "config.yml"
    text = path.read_text().replace("  story: true", f"  story: {tier}")
    path.write_text(f"lifecycle_command: {command}\n" + text)
    g("add", "-A")
    g("commit", "-qm", "configure lifecycle")


def test_runner_uses_exact_quoted_argv_and_never_a_shell(tmp_path):
    command, log = recorder(tmp_path)
    assert verify_commands("story-042", 'Verify: printf "fixed value"', False)[1] == [
        ["printf", "fixed value"]
    ]
    assert run(command, "story-close", "story-042") == ""
    assert entries(log)[0]["argv"] == ["fixed value", "story-close", "story-042"]

    sentinel = tmp_path / "shell-payload"
    refusal = run(f"{command} > {sentinel}", "story-close", "story-042")
    assert "story-close" in refusal and command.split()[0] in refusal
    assert not sentinel.exists()
    assert run("", "story-close", "story-042") == ""


def test_story_close_runs_after_gates_and_before_merge(tmp_path):
    command, log = recorder(tmp_path)
    repo, env, g = make_repo(tmp_path)
    configure(repo, g, command)
    before = g("rev-parse", "main").stdout.strip()
    assert story(repo, env, "review").returncode == 0
    result = story(repo, env, "land")
    assert result.returncode == 0, result.stderr + result.stdout
    assert entries(log) == [{"argv": ["fixed value", "story-close", "story-042"], "main": before}]
    assert g("rev-parse", "main").stdout.strip() != before


def test_red_story_tier_never_calls_project_code(tmp_path):
    command, log = recorder(tmp_path)
    repo, env, g = make_repo(tmp_path)
    configure(repo, g, command, tier="false")
    assert story(repo, env, "review").returncode == 0
    result = story(repo, env, "land")
    assert result.returncode == 2 and "test tier red" in result.stderr
    assert entries(log) == []


def test_retry_after_later_local_failure_repeats_the_same_argv(tmp_path):
    command, log = recorder(tmp_path)
    repo, env, g = make_repo(tmp_path)
    configure(repo, g, command)
    assert story(repo, env, "review").returncode == 0
    argv = [sys.executable, str(CLOSE), "story", "story-042", "land", "--merge-mode", "pr"]
    for _ in range(2):
        result = subprocess.run(argv, cwd=repo, env=env, capture_output=True, text=True)
        assert result.returncode == 2 and "gh CLI" in result.stderr
    assert [entry["argv"] for entry in entries(log)] == [
        ["fixed value", "story-close", "story-042"],
        ["fixed value", "story-close", "story-042"],
    ]


def test_free_land_does_not_emit_a_story_event(tmp_path):
    command, log = recorder(tmp_path)
    repo, env, g = free_repo(tmp_path)
    configure(repo, g, command)
    assert free(repo, env, "fix-typo", "start").returncode == 0
    (repo / "free.py").write_text("FREE = 1\n")
    g("add", "-A")
    g("commit", "-qm", "free change")
    assert free(repo, env, "fix-typo", "review").returncode == 0
    result = free(repo, env, "fix-typo", "land")
    assert result.returncode == 0, result.stderr + result.stdout
    assert entries(log) == []
