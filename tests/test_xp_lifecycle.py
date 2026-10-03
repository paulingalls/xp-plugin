"""Public lifecycle routes preserve owners and leave previews inert."""

import subprocess
import sys

import pytest
from sprint_helpers import PLUGIN, make_repo, snapshot
from test_milestone import active_plan, condition
from test_open_sprint import falsifier, fixture, hook

XP = PLUGIN / "scripts/xp.py"


def invoke(repo, env, *args, script=XP):
    return subprocess.run(
        [sys.executable, str(script), *args], cwd=repo, env=env, capture_output=True, text=True
    )


def test_open_runs_only_open_lifecycle(tmp_path):
    repo, env, g, branch = fixture(tmp_path)
    output = hook(repo, tmp_path)
    batch = falsifier(tmp_path)
    g("add", "-A")
    g("commit", "-qm", "configure lifecycle")
    result = invoke(repo, env, "sprint", "2", "open")
    assert result.returncode == 0, result.stderr
    assert branch.read_text() == "sprint-002\n"
    assert output.read_text() == "sprint-open 2"
    assert not batch.exists()


@pytest.mark.parametrize("script", [XP, PLUGIN / "scripts/close.py"])
def test_help_and_previews_leave_repository_and_data_unchanged(tmp_path, script):
    command, sentinel = condition(tmp_path)
    repo, env, _g = make_repo(tmp_path, plan=active_plan(command))
    before = snapshot(tmp_path)
    result = invoke(repo, env, "sprint", "2", "milestone-done", "--dry-run", script=script)
    assert result.returncode == 0, result.stderr
    assert not sentinel.exists()
    assert snapshot(tmp_path) == before
    result = invoke(repo, env, "--help", script=script)
    assert result.returncode == 0, result.stderr
    assert snapshot(tmp_path) == before


def test_primary_routes_dispatch_existing_operations(tmp_path):
    command, sentinel = condition(tmp_path)
    repo, env, _g = make_repo(tmp_path, plan=active_plan(command))
    result = invoke(repo, env, "sprint", "2", "milestone-done")
    assert result.returncode == 0, result.stderr
    assert sentinel.read_text() == "green"
    assert "[done]" in (tmp_path / "data/plan.md").read_text().splitlines()[1]


@pytest.mark.parametrize(
    "kind,identity,action",
    [
        ("story", "story-042", "review"),
        ("story", "story-042", "land"),
        ("free", "patch", "start"),
        ("sprint", "2", "open"),
        ("sprint", "2", "review"),
    ],
)
def test_role_refusal_precedes_all_effects(tmp_path, kind, identity, action):
    repo, env, _g = make_repo(tmp_path)
    before = snapshot(tmp_path)
    result = invoke(repo, env | {"XP_ROLE": "executor"}, kind, identity, action)
    assert result.returncode == 2 and "only the lead" in result.stderr
    assert snapshot(tmp_path) == before


def test_emitted_next_actions_use_public_surface(tmp_path):
    import re
    import shlex

    from story_review_helpers import flow_repo

    repo, env, _git, key, events, _hooks = flow_repo(tmp_path, scenario="closer-blocked")
    result = invoke(repo, env, "story", key, "review")
    assert result.returncode == 2
    command = next(c for c in re.findall(r"`([^`]+)`", result.stderr) if c.startswith("xp.py "))
    before = events.read_bytes()
    retried = invoke(repo, env, *shlex.split(command)[1:])
    assert retried.returncode == 2 and events.read_bytes() == before


@pytest.mark.meta
@pytest.mark.parametrize("fault", ["role", "preview", "opening"])
def test_lifecycle_guards_detect_target_faults(tmp_path, monkeypatch, fault):
    import shutil

    def guarantee(root):
        root.mkdir()
        if fault == "role":
            test_role_refusal_precedes_all_effects(root, "sprint", "2", "open")
        elif fault == "preview":
            test_help_and_previews_leave_repository_and_data_unchanged(root, XP)
        else:
            test_open_runs_only_open_lifecycle(root)

    guarantee(tmp_path / "control")
    installed = tmp_path / "installed"
    shutil.copytree(PLUGIN, installed)
    if fault == "preview":
        path = installed / "scripts/close/milestone.py"
        old = "    if dry_run:\n"
        new = "    if False:\n"
    else:
        path = installed / "scripts/xp.py"
        old, new = (
            ('    if role != "lead":', "    if False:")
            if fault == "role"
            else (
                "return cmd_open(a.sprint_id, a.dry_run)",
                "return sprint_close.prepare_close(a.sprint_id, a.dry_run)",
            )
        )
    text = path.read_text()
    assert old in text
    path.write_text(text.replace(old, new, 1))
    monkeypatch.setattr(sys.modules[__name__], "XP", installed / "scripts/xp.py")
    # invoke's default must follow the candidate, too.
    monkeypatch.setattr(invoke, "__kwdefaults__", {"script": installed / "scripts/xp.py"})
    with pytest.raises(AssertionError):
        guarantee(tmp_path / "mutant")


def test_land_preview_does_not_fetch_or_create_data_directories(tmp_path):
    from sprint_helpers import make_repo, record_reviews
    from test_sprint_tier_receipt import add_origin

    repo, env, g = make_repo(tmp_path)
    add_origin(tmp_path, repo, env, g)
    record_reviews(tmp_path, repo, env)
    fetch = repo / ".git/FETCH_HEAD"
    fetch.unlink(missing_ok=True)
    before = snapshot(tmp_path / "data")
    dirs = {p.relative_to(tmp_path / "data") for p in (tmp_path / "data").rglob("*")}
    result = invoke(repo, env, "sprint", "2", "land", "--dry-run")
    assert result.returncode == 0, result.stderr
    assert not fetch.exists()
    assert snapshot(tmp_path / "data") == before
    assert {p.relative_to(tmp_path / "data") for p in (tmp_path / "data").rglob("*")} == dirs


@pytest.mark.parametrize(
    "kind,action", [("story", "repair"), ("story", "salvage"), ("free", "repair")]
)
def test_retired_saved_actions_refuse_with_executable_recovery(tmp_path, kind, action):
    import shlex

    repo, env, _g = make_repo(tmp_path)
    before = snapshot(tmp_path)
    result = invoke(repo, env, kind, "story-042", action, script=PLUGIN / "scripts/close.py")
    assert result.returncode == 2 and "retired" in result.stderr
    recovery = next(
        c for c in __import__("re").findall(r"`([^`]+)`", result.stderr) if c.startswith("xp.py ")
    )
    recovered = invoke(repo, env, *shlex.split(recovery)[1:], "--dry-run")
    assert recovered.returncode == 2 and "refused:" in recovered.stderr
    assert "usage:" not in recovered.stderr and "Traceback" not in recovered.stderr
    assert snapshot(tmp_path) == before
