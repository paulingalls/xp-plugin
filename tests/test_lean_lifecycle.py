"""Consumer adoption and the complete public lifecycle with real Git transitions."""

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from sprint_helpers import PLUGIN, launches, staged_stub
from test_xp_lifecycle import XP, invoke

SAVED = Path(__file__).parent / "fixtures/saved_lifecycle"


def test_saved_artifacts_adopt_without_reauthoring(tmp_path):
    from sprint_helpers import make_repo
    from test_session_recovery_command import printed_command

    repo, env, _g = make_repo(tmp_path)
    data = Path(env["XP_DATA"])
    for name in ("plan.md", "work.md"):
        shutil.copy2(SAVED / name, data / name)
    before = {n: (data / n).read_bytes() for n in ("plan.md", "work.md")}
    (data / "env.json").write_text(
        json.dumps({"plugin_root": "/gone", "plugin_version": "old", "keep": 7})
    )
    installed = tmp_path / "installed"
    shutil.copytree(PLUGIN, installed)
    env = env | {"PATH": f"{Path(sys.executable).parent}:" + env["PATH"]}
    start = subprocess.run(
        [sys.executable, str(installed / "scripts/session_start.py")],
        cwd=repo,
        env=env,
        input="{}",
        text=True,
        capture_output=True,
    )
    assert start.returncode == 0, start.stderr
    recovered = subprocess.run(
        ["/bin/sh", "-c", printed_command(start.stdout)],
        cwd=repo,
        env=env,
        text=True,
        capture_output=True,
    )
    assert recovered.returncode == 0, recovered.stderr
    pointer = json.loads((data / "env.json").read_text())
    assert pointer["plugin_root"] == str(installed) and pointer["keep"] == 7
    assert (
        pointer["plugin_version"]
        == json.loads((installed / ".claude-plugin/plugin.json").read_text())["version"]
    )
    assert {n: (data / n).read_bytes() for n in before} == before
    from sprint_close import grouped_batch

    grouped, _source = grouped_batch(data)
    assert grouped == {}
    from falsifier_batch import ledger

    records = ledger(data)
    assert len(records) == 1 and records[0].state == "RESOLVED"
    assert records[0].eid == "b5cfb5e9"


@pytest.mark.parametrize("action", ["review", "land", "milestone-done", "salvage", "post-merge"])
@pytest.mark.parametrize("role", ["lead", "executor"])
def test_saved_commands_delegate_without_bypassing_guards(tmp_path, action, role):
    from sprint_helpers import make_repo, snapshot

    results = []
    for name, script in [("old", PLUGIN / "scripts/close.py"), ("new", XP)]:
        root = tmp_path / name
        root.mkdir()
        repo, env, _g = make_repo(root)
        before = snapshot(root / "data")
        result = invoke(
            repo, env | {"XP_ROLE": role}, "sprint", "2", action, "--dry-run", script=script
        )
        assert snapshot(root / "data") == before
        results.append(result.returncode)
    assert results[0] == results[1]
    if role != "lead":
        assert results == [2, 2]


def test_complete_flow_has_only_required_stages(tmp_path):
    from spawn_helpers import make_repo, spawn
    from sprint_helpers import stage_key
    from test_card_update_contract import CHANGES, edited_stages

    repo, env, g = make_repo(tmp_path, status="planned", files="src/thing.py, src/other.py")
    config = repo / ".xp/config.yml"
    config.write_text(
        config.read_text().replace("story: true", "story: true\n  full: true")
        + "version_files: none\nsprint_cap: 6\ndebt_budget: 0.2\n"
    )
    (repo / "src").mkdir()
    (repo / "src/thing.py").write_text("A = 1\n")
    g("add", "-A")
    assert g("commit", "-qm", "consumer source").returncode == 0
    assert g("checkout", "-q", "main").returncode == 0
    assert g("merge", "--ff-only", "elsewhere").returncode == 0
    assert g("checkout", "-qb", "sprint-001").returncode == 0
    data = Path(env["XP_DATA"])
    (data / "sprint_branch").unlink()
    # Opening must preserve unscheduled work outside the selected sprint.
    plan = data / "plan.md"
    plan.write_text(plan.read_text() + "\n### Parking\n#### story-099 — later   [retired]\n")
    from test_sprint_planning_flow import stub

    (tmp_path / "bin").mkdir(exist_ok=True)
    stub(tmp_path, "claude")
    slate = subprocess.run(
        [sys.executable, str(PLUGIN / "scripts/slate_review.py"), "1"],
        cwd=repo,
        env=env,
        text=True,
        capture_output=True,
    )
    assert slate.returncode == 0, slate.stderr
    opened = invoke(repo, env, "sprint", "1", "open")
    assert opened.returncode == 0, opened.stderr
    seen = edited_stages(tmp_path, [CHANGES["ac"], CHANGES["single"]])
    executed = spawn(repo, env, "story-042")
    assert executed.returncode == 0, executed.stderr
    events = [json.loads(line) for line in seen.read_text().splitlines()]
    assert [e["role"] for e in events] == ["planner", "plan-reviewer", "teammate", "reviewer"]
    assert "REVIEWED-AC" in events[2]["prompt"]
    tree = data / "worktrees/story-042"
    assert (tree / "src/thing.py").read_text() == "A = 1\n\nDONE = True\n"
    assert "story-099 — later   [retired]" in plan.read_text()
    landed = invoke(tree, env, "story", "story-042", "land")
    assert landed.returncode == 0, landed.stderr
    assert not tree.exists()
    assert (repo / "src/thing.py").read_text() == "A = 1\n\nDONE = True\n"
    assert "story-042 — demo story   [done]" in plan.read_text()
    (tmp_path / "launches.jsonl").unlink(missing_ok=True)
    staged_stub(tmp_path)
    reviewed = invoke(repo, env, "sprint", "1", "review")
    assert reviewed.returncode == 0, reviewed.stderr
    keys = [stage_key(e["stdin"]) for e in launches(tmp_path)]
    assert keys and all(key.startswith("find-") for key in keys)
    from test_land_push_refusal import working_gh
    from test_sprint_tier_receipt import add_origin

    add_origin(tmp_path, repo, env, g)
    working_gh(tmp_path, env)
    prepared = invoke(repo, env, "sprint", "1", "land")
    assert prepared.returncode == 0, prepared.stderr
    assert not (data / "releases/sprint-1.json").exists()
    assert g("checkout", "-q", "main").returncode == 0
    assert g("merge", "--no-ff", "sprint-001", "-m", "merge release").returncode == 0
    released = invoke(repo, env, "sprint", "1", "post-merge")
    assert released.returncode == 0, released.stderr
    assert (data / "releases/sprint-1.json").is_file()
    assert not (data / "sprint_branch").exists()


def test_review_stops_on_open_red_without_launching_readers(tmp_path):
    from sprint_helpers import make_repo, work

    repo, env, _g = make_repo(tmp_path)
    assert (
        work(
            repo,
            env,
            "bug",
            "--claim",
            "constructed open obligation",
            "--falsifier",
            "false",
            "--files",
            "src.py",
        ).returncode
        == 0
    )
    result = invoke(repo, env, "sprint", "2", "review")
    assert result.returncode == 2 and "batch falsifier RED" in result.stderr
    assert not launches(tmp_path)
    assert not (tmp_path / "data/markers/sprint/2.json").exists()


@pytest.mark.meta
@pytest.mark.parametrize("fault", ["rewrite-history", "skip-batch", "misroute-land"])
def test_adoption_and_flow_guards_detect_target_faults(tmp_path, monkeypatch, fault):
    import sys

    def guarantee(root):
        root.mkdir()
        if fault == "rewrite-history":
            test_saved_artifacts_adopt_without_reauthoring(root)
        elif fault == "skip-batch":
            test_review_stops_on_open_red_without_launching_readers(root)
        else:
            test_complete_flow_has_only_required_stages(root)

    guarantee(tmp_path / "control")
    installed = tmp_path / "installed"
    shutil.copytree(PLUGIN, installed)
    if fault == "rewrite-history":
        path = installed / "scripts/session_start.py"
        old = "def main(data: dict) -> int:\n"
        new = old + '    (data_root() / "work.md").write_text("rewritten history\\n")\n'
    elif fault == "skip-batch":
        path = installed / "scripts/close/sprint_review.py"
        old, new = "if error := prepare_close(sprint_id, dry_run):", "if False:"
    else:
        path = installed / "scripts/xp.py"
        old, new = (
            "return cmd_land(a.story_id, mode, a.dry_run)",
            "return cmd_review(a.story_id, a.dry_run)",
        )
    source = path.read_text()
    assert old in source
    path.write_text(source.replace(old, new, 1))
    monkeypatch.setattr(sys.modules[__name__], "PLUGIN", installed)
    from test_xp_lifecycle import invoke

    monkeypatch.setattr(invoke, "__kwdefaults__", {"script": installed / "scripts/xp.py"})
    with pytest.raises(AssertionError):
        guarantee(tmp_path / "mutant")
