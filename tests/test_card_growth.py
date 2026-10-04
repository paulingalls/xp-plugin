"""Ordinary adjustments retain completed work and validate current obligations."""

from pathlib import Path

import pytest
from card_adjustment_support import adjust, command, plugin
from close_helpers import close, launches, make_repo
from story_review_helpers import checkpoint, flow_repo, invoke
from test_spawn_resume import finished_story, resume


@pytest.mark.parametrize("change", ["context", "files", "reorder", "replace"])
def test_locked_adjustments_continue_completed_work(tmp_path, change):
    repo, env, _git, tree, marker = finished_story(tmp_path)
    import json
    import subprocess

    state = json.loads(marker.read_text())
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=tree)
    first, second = tmp_path / "first", tmp_path / "second"
    order = tmp_path / "order"
    one = f"sh -c 'echo first >> {order}; touch {first}'"
    two = f"sh -c 'echo second >> {order}; touch {second}'"
    old = f"{one} && {two}"
    adjust(repo, env, [("Verify: true", f"Verify: {old}")])
    replacements = {
        "context": [("demo.", "corrected context.")],
        "files": [("Files: src/thing.py", "Files: src/correct.py")],
        "reorder": [(old, f"{two} && {one}")],
        "replace": [(old, two)],
    }
    adjust(repo, env, replacements[change])
    assert resume(repo, env, "--dry-run").returncode == 0
    result = resume(repo, env)
    assert result.returncode == 0, result.stderr
    after = json.loads(marker.read_text())
    assert order.read_text().splitlines() == (
        ["second", "first"]
        if change == "reorder"
        else ["second"]
        if change == "replace"
        else ["first", "second"]
    )
    assert second.exists()
    assert first.exists() == (change != "replace")
    assert subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=tree) == head
    assert after["stages"]["executor"] == state["stages"]["executor"]
    assert after["stages"]["planner"] == state["stages"]["planner"]


def test_current_verify_red_cannot_inherit_previous_green(tmp_path):
    repo, env, git = make_repo(tmp_path)
    assert close(repo, env, "review").returncode == 0
    head = git("rev-parse", "main").stdout
    sentinel = tmp_path / "current-red"
    gate = tmp_path / "gate"
    gate.write_text(f"#!/bin/sh\ntouch {sentinel}\nexit 7\n")
    gate.chmod(0o755)
    adjust(repo, env, [("Verify: true", f"Verify: {gate}")])
    result = close(repo, env, "land")
    assert result.returncode == 2, result.stdout + result.stderr
    assert sentinel.exists()
    assert git("rev-parse", "main").stdout == head
    assert "[in-progress]" in (tmp_path / "data/plan.md").read_text()
    import json

    evidence = json.loads((tmp_path / "data/markers/story-042.land-red.json").read_text())
    assert str(gate) in str(evidence)


@pytest.mark.parametrize("field", ["title", "executor", "decision"])
def test_reserved_edit_cannot_continue_without_amendment(tmp_path, field):
    repo, env, _git = make_repo(tmp_path)
    replacements = {
        "title": [("demo story", "different story")],
        "executor": [("Context: demo.", "Context: demo.\nExecutor: codex/model")],
        "decision": [("Context: demo.", "Context: demo.\nDecision: changed choice")],
    }
    adjust(repo, env, replacements[field])
    result = close(repo, env, "review")
    assert result.returncode == 2 and "amend" in result.stderr
    assert launches(tmp_path) == []


@pytest.mark.parametrize("failure", ["write", "replace"])
def test_atomic_edit_failure_retains_shared_plan(tmp_path, monkeypatch, failure):
    from plan_writer import locked_edit

    path = tmp_path / "plan.md"
    original = "#### story-042 [in-progress]\nContext: prior\n#### story-043 [done]\nSIBLING\n"
    path.write_text(original)
    write = Path.write_text

    def broken_write(self, text, *args, **kwargs):
        if self.name.endswith(".tmp") or self == path:
            write(self, text[:8])
            raise OSError("partial write")
        return write(self, text, *args, **kwargs)

    def broken_replace(self, target):
        raise OSError("replace failure")

    monkeypatch.setattr(
        Path,
        "write_text" if failure == "write" else "replace",
        broken_write if failure == "write" else broken_replace,
    )
    with pytest.raises(OSError):
        locked_edit(path, tmp_path / "lock", lambda text: text.replace("prior", "current"))
    assert path.read_text() == original


@pytest.mark.parametrize("harness", ["claude", "codex"])
@pytest.mark.parametrize("producer", ["fixer", "closer"])
def test_adjusted_report_correction_preserves_committed_work(tmp_path, harness, producer):
    repo, env, git, key, events, hooks = flow_repo(
        tmp_path, harness, scenario="malformed-" + producer
    )
    binary = tmp_path / "bin" / harness
    binary.write_text(
        binary.read_text().replace(
            "if stage=='fixer':",
            "if stage=='fixer' and 'Correct only the incomplete report' not in prompt:",
        )
    )
    assert invoke(repo, env, key).returncode == 2
    before = checkpoint(env, key)
    saved = {s["path"]: Path(s["path"]).read_bytes() for s in before["stages"].values()}
    head = git("rev-parse", "HEAD").stdout
    sentinel = tmp_path / "verify-current"
    adjust(
        repo,
        env,
        [
            ("Context: demo.", "Context: corrected obligations."),
            ("Verify: true", f"Verify: touch {sentinel}"),
        ],
    )
    count = events.read_bytes()
    from test_story_review_recovery import worktree

    tree = worktree(repo, env, git, key)
    result = command(repo, env, "spawn.py", "resume", key)
    assert result.returncode == 2 and events.read_bytes() == count
    binary.write_text(binary.read_text().replace("'malformed-" + producer + "'", "'fixed'"))
    result = invoke(tree, env, key)
    assert result.returncode == 0, result.stderr
    after = checkpoint(env, key)
    assert after["id"] == before["id"]
    assert after["start"] == before["start"]
    assert all(Path(p).read_bytes() == data for p, data in saved.items())
    import subprocess

    assert subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=tree).decode() == head
    assert hooks.read_text().splitlines() == ["hook"]
    assert events.read_text().splitlines() == (
        ["solution", "fixer", "fixer", "closer"]
        if producer == "fixer"
        else ["solution", "fixer", "closer", "closer"]
    )
    assert sentinel.exists()
    prompt = Path(str(events) + "." + producer + ".prompt").read_text()
    assert "corrected obligations" in prompt and "reviewed" in prompt


@pytest.mark.parametrize("state", ["completed", "validation-red"])
def test_adjusted_completed_review_rechecks_obligations(tmp_path, state):
    import json
    import shutil
    import subprocess

    root = tmp_path / "consumer"
    root.mkdir()
    repo, env, _git, tree, _marker = finished_story(root)
    donor = tmp_path / "harness"
    donor.mkdir()
    _repo, _env, _git, key, events, hooks = flow_repo(donor, scenario="fixed")
    shutil.copyfile(donor / "bin/claude", root / "bin/claude")
    shutil.copyfile(_repo / ".git/hooks/pre-commit", repo / ".git/hooks/pre-commit")
    (repo / ".git/hooks/pre-commit").chmod(0o755)
    (tree / "src").mkdir(exist_ok=True)

    if state == "validation-red":
        adjust(repo, env, [("Verify: true", "Verify: false")])
    assert invoke(tree, env, key).returncode == (0 if state == "completed" else 2)
    before = checkpoint(env, key)
    reports = {s["path"]: Path(s["path"]).read_bytes() for s in before["stages"].values()}
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=tree).decode()
    sentinel = tmp_path / "current-command"
    gate = tmp_path / "gate"
    gate.write_text(f"#!/bin/sh\ntouch {sentinel}\nexit {7 if state == 'completed' else 0}\n")
    gate.chmod(0o755)
    adjust(
        repo,
        env,
        [
            ("Verify: " + ("true" if state == "completed" else "false"), f"Verify: {gate}"),
            ("Context: demo.", "Context: updated obligations."),
        ],
    )
    binary = root / "bin/claude"
    binary.write_text(binary.read_text().replace("'fixed'", "'clean'"))
    preview = command(tree, env, "spawn.py", "resume", key, "--dry-run")
    assert preview.returncode == 0, preview.stderr
    result = command(tree, env, "spawn.py", "resume", key)
    if state == "validation-red":
        assert result.returncode == 2 and events.read_text().splitlines() == [
            "solution",
            "fixer",
            "closer",
        ]
        result = invoke(tree, env, key)
    assert result.returncode == 2, result.stderr
    after = checkpoint(env, key)
    assert after["id"] != before["id"]
    assert sentinel.exists()
    assert hooks.read_text().splitlines() == ["hook"]
    assert events.read_text().splitlines() == ["solution", "fixer", "closer", "solution"]
    assert all(Path(p).read_bytes() == data for p, data in reports.items())
    import subprocess

    assert subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=tree).decode() == head
    handoff = json.loads((Path(env["XP_DATA"]) / "plans" / f"{key}.handoff.json").read_text())
    assert handoff["checkpoint"]["review_history"][-1] == before
    prompt = Path(str(events) + ".solution.prompt").read_text()
    assert "updated obligations" in prompt and "--- reviewed" in prompt
    if state == "validation-red":
        assert after["status"] == "awaiting-disposition"
        assert after["validation"][0] == before["validation"][0]
        result = invoke(
            tree, env, key, "acknowledge-validation", "--reason", "obsolete command replaced"
        )
        assert result.returncode == 0, result.stderr


def test_adjusted_interrupted_stage_resumes_completed_work(tmp_path):
    from forward_progress_kill_support import interrupted_stage
    from plan_review_install import installed_launch

    launch = installed_launch(tmp_path)
    sentinel = tmp_path / "current-verify"

    def corrected(repo, env, *args):
        adjust(
            repo,
            env,
            [
                ("Context: demo.", "Context: corrected after interruption."),
                ("Files: src/thing.py, src/other.py", "Files: src/thing.py"),
                ("Verify: true", f"Verify: touch {sentinel}"),
            ],
        )
        preview = launch(repo, env, *args, "--dry-run")
        assert preview.returncode == 0, preview.stderr
        return launch(repo, env, *args)

    interrupted_stage(tmp_path, corrected)
    assert sentinel.exists()


@pytest.mark.parametrize("harness", ["claude", "codex"])
def test_agent_adjustment_instructions_execute(tmp_path, harness):
    import re
    import shlex
    import subprocess

    repo, env, _git, key, events, hooks = flow_repo(tmp_path, harness, scenario="malformed-fixer")
    import sys

    (tmp_path / "bin/python3").symlink_to(sys.executable)
    binary = tmp_path / "bin" / harness
    binary.write_text(
        binary.read_text().replace(
            "if stage=='fixer':",
            "if stage=='fixer' and 'Correct only the incomplete report' not in prompt:",
        )
    )
    assert invoke(repo, env, key).returncode == 2
    candidate = tmp_path / "candidate.md"
    import os
    from contextlib import chdir
    from unittest.mock import patch

    from prompt import executor_prompt

    with chdir(repo), patch.dict(os.environ, env):
        prompt = executor_prompt(
            (Path(env["XP_DATA"]) / "plan.md").read_text(), key, "", plugin(), plugin(), False
        )
    snapshot, edit = [c for c in re.findall(r"`([^`]+)`", prompt) if "scripts/work.py" in c]
    snapshot = snapshot.replace("STORY_ID", key).replace("/absolute/candidate.md", str(candidate))
    result = subprocess.run(
        shlex.split(snapshot), cwd=repo, env=env, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    digest = re.search(r"^digest: (\w+)$", result.stdout, re.M).group(1)
    sentinel = tmp_path / "instruction-verify"
    candidate.write_text(candidate.read_text().replace("Verify: true", f"Verify: touch {sentinel}"))
    edit = (
        edit.replace("STORY_ID", key)
        .replace("/absolute/candidate.md", str(candidate))
        .replace("DIGEST", digest)
        .replace("STATUS", "in-progress")
    )
    assert subprocess.run(shlex.split(edit), cwd=repo, env=env).returncode == 0
    from test_story_review_recovery import worktree

    tree = worktree(repo, env, _git, key)
    prompt = Path(str(events) + ".solution.prompt").read_text().replace("STORY_ID", key)
    routes = [
        [sys.executable, str(plugin() / "scripts" / parts[0]), *parts[1:]]
        for c in re.findall(r"`([^`]+)`", prompt)
        if (parts := shlex.split(c)) and parts[0] in ("spawn.py", "xp.py")
    ]
    resumed = subprocess.run(routes[0], cwd=repo, env=env, capture_output=True, text=True)
    assert resumed.returncode == 2
    binary.write_text(binary.read_text().replace("'malformed-fixer'", "'fixed'"))
    reviewed = subprocess.run(routes[1], cwd=tree, env=env, capture_output=True, text=True)
    assert reviewed.returncode == 0, reviewed.stderr
    assert sentinel.exists() and hooks.read_text().splitlines() == ["hook"]
    assert events.read_text().splitlines() == ["solution", "fixer", "fixer", "closer"]
    for script in ("work.py", "spawn.py", "xp.py"):
        assert command(repo, env, script, "--help").returncode == 0
