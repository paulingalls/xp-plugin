import json
import subprocess
import sys
import types

import pytest
from test_land import commit, fake_gh, git, make_project, manifest, ns
from xpcore import config, launch, sprint

HOOK = "#!/bin/sh\ntest -f trunk.txt || exit 1\necho ran >> {log}\n"
SLATE = "## Sprint 1 — s\n\n#### story-001 — a   [{status}]\nAcceptance: true\n"


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """sprint-001 carries the hook and the bump; trunk moved since, adding trunk.txt."""
    root, data = make_project(tmp_path, monkeypatch)
    (data / "plan.md").write_text(SLATE.format(status="done"))
    hooklog = tmp_path / "hook.log"
    git(root, "switch", "-qc", "sprint-001")
    (data / "sprint_branch").write_text("sprint-001\n")
    (root / ".githooks").mkdir()
    (root / ".githooks" / "sprint").write_text(HOOK.format(log=hooklog))
    (root / ".githooks" / "sprint").chmod(0o755)
    commit(root, manifest("1.2.0"), "sprint work")
    git(root, "switch", "-q", "main")
    commit(root, {"trunk.txt": "t\n"}, "trunk moved")
    git(root, "switch", "-q", "sprint-001")
    return root, data, hooklog


def merge_on_trunk(root):
    git(root, "switch", "-q", "main")
    git(root, "merge", "-q", "--no-ff", "sprint-001", "-m", "PR")


def test_open_refuses_off_branch_then_records(tmp_path, monkeypatch, capsys):
    root, data = make_project(tmp_path, monkeypatch)
    (data / "plan.md").write_text("## Sprint 2 — s\n")
    with pytest.raises(SystemExit) as exit_:
        sprint.cmd_sprint_open(ns("2"))
    assert exit_.value.code == 2 and "not sprint-002" in capsys.readouterr().err
    git(root, "switch", "-qc", "sprint-002")
    assert sprint.cmd_sprint_open(ns("2")) == 0
    assert config.sprint_branch() == "sprint-002"


def test_land_tests_the_trial_merge_and_post_merge_skips_that_tree(repo, tmp_path, monkeypatch):
    root, data, hooklog = repo
    gh = fake_gh(tmp_path, monkeypatch)
    assert sprint.cmd_sprint_land(ns("1")) == 0
    assert hooklog.read_text() == "ran\n"  # the hook found trunk.txt: it ran on the merge
    assert "--base main --head sprint-001 --fill" in gh.read_text()
    assert not (root / "trunk.txt").exists()
    merge_on_trunk(root)
    assert sprint.cmd_sprint_post_merge(ns("1")) == 0
    assert hooklog.read_text() == "ran\n"
    assert git(root, "cat-file", "-t", "v1.2.0") == "tag"
    assert json.loads((data / "sprints" / "1" / "release.json").read_text())["version"] == "1.2.0"
    assert config.sprint_branch() == "" and git(root, "branch", "--list", "sprint-001") == ""


def test_post_merge_refuses_in_progress_then_reruns_a_changed_tree(repo, capsys):
    root, data, hooklog = repo
    merge_on_trunk(root)
    (data / "sprints" / "1").mkdir(parents=True)
    (data / "sprints" / "1" / "land.json").write_text(json.dumps({"tested_tree": "0" * 40}))
    (data / "plan.md").write_text(SLATE.format(status="in-progress"))
    with pytest.raises(SystemExit):
        sprint.cmd_sprint_post_merge(ns("1"))
    assert "story-001 still in-progress" in capsys.readouterr().err
    (data / "plan.md").write_text(SLATE.format(status="done"))
    assert sprint.cmd_sprint_post_merge(ns("1")) == 0
    assert hooklog.read_text() == "ran\n"


def test_review_runs_every_angle_then_one_executor_with_all_findings(repo, monkeypatch):
    data = repo[1]
    calls = []

    def run_agent(role, prompt, cwd, log_id, **_):
        calls.append((role, prompt))
        return subprocess.CompletedProcess([], 0, f"finding from {log_id}", "")

    bundle = types.SimpleNamespace(prompt=lambda role, **k: f"{role}\n{k.get('findings', '')}")
    monkeypatch.setitem(sys.modules, "xpcore.bundle", bundle)
    monkeypatch.setattr(launch, "run_agent", run_agent)
    assert sprint.cmd_sprint_review(ns("1")) == 0
    angles = sorted(p.stem for p in (config.plugin_root() / "angles").glob("*.md"))
    written = sorted(p.name for p in (data / "sprints" / "1").glob("review-1.*.md"))
    assert written == [f"review-1.{a}.md" for a in angles] and len(calls) == len(angles) + 1
    role, prompt = calls[-1]
    assert role == "executor" and all(f"reviewer-1-{a}" in prompt for a in angles)
