import json
import subprocess

import pytest
from test_land import commit, fake_gh, git, make_project, manifest, ns
from xpcore import bundle, config, launch, release, sprint

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


def test_land_tests_the_trial_merge_and_post_merge_skips_that_tree(
    repo, tmp_path, monkeypatch, capsys
):
    root, data, hooklog = repo
    gh = fake_gh(tmp_path, monkeypatch)
    (data / "sprints" / "1").mkdir(parents=True)
    (data / "sprints" / "1" / "review-1.tests.md").write_text("finding\n")
    assert sprint.cmd_sprint_land(ns("1")) == 0
    assert hooklog.read_text() == "ran\n"  # the hook found trunk.txt: it ran on the merge
    assert "--base main --head sprint-001 --title Sprint 1 --body " in gh.read_text()
    assert "v1.2.0" in gh.read_text() and "review-1.tests.md" in gh.read_text()
    assert not (root / "trunk.txt").exists()
    git(root, "switch", "-q", "main")
    with pytest.raises(SystemExit):
        sprint.cmd_sprint_post_merge(ns("1"))
    err = capsys.readouterr().err
    assert "sprint-001 is not merged into main" in err and "squash- or rebase-merged" in err
    assert git(root, "tag", "--list", "v1.2.0") == "" and config.sprint_branch() == "sprint-001"
    assert git(root, "branch", "--list", "sprint-001")
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


def test_squash_merged_sprint_post_merges_and_says_merge_commits_are_preferred(
    repo, tmp_path, monkeypatch, capsys
):
    root, _, hooklog = repo
    fake_gh(tmp_path, monkeypatch)
    assert sprint.cmd_sprint_land(ns("1")) == 0
    git(root, "switch", "-q", "main")
    git(root, "merge", "-q", "--squash", "sprint-001")
    git(root, "commit", "-qm", "Sprint 1 (#1)")
    assert sprint.cmd_sprint_post_merge(ns("1")) == 0
    assert "squash-merged" in capsys.readouterr().out and hooklog.read_text() == "ran\n"
    assert git(root, "cat-file", "-t", "v1.2.0") == "tag"
    assert config.sprint_branch() == "" and git(root, "branch", "--list", "sprint-001") == ""


def test_post_merge_rerun_after_the_tag_finishes_without_tagging_again(repo, monkeypatch):
    root, data, _ = repo
    merge_on_trunk(root)
    (data / "sprints" / "1").mkdir(parents=True)
    tree = git(root, "rev-parse", "HEAD^{tree}")
    (data / "sprints" / "1" / "land.json").write_text(json.dumps({"tested_tree": tree}))
    with monkeypatch.context() as m:
        m.setattr(release, "write_release_record", lambda *a: 1 / 0)
        with pytest.raises(ZeroDivisionError):
            sprint.cmd_sprint_post_merge(ns("1"))
    assert git(root, "tag", "--points-at", "HEAD") == "v1.2.0"
    assert config.sprint_branch() == "sprint-001"
    assert sprint.cmd_sprint_post_merge(ns("1")) == 0
    assert git(root, "tag", "--points-at", "HEAD") == "v1.2.0"
    assert json.loads((data / "sprints" / "1" / "release.json").read_text())["tag"] == "v1.2.0"
    assert config.sprint_branch() == "" and git(root, "branch", "--list", "sprint-001") == ""


def test_plan_names_the_branch_to_cut(repo, monkeypatch, capsys):
    run = subprocess.CompletedProcess([], 0, "slate ok", "")
    monkeypatch.setattr(bundle, "prompt", lambda role, **k: role)
    monkeypatch.setattr(launch, "run_agent", lambda *a, **k: run)
    assert sprint.cmd_sprint_plan(ns("1")) == 0
    assert "`git switch -c sprint-001 main`" in capsys.readouterr().out


def test_review_runs_every_angle_then_one_executor_with_all_findings(repo, monkeypatch, capsys):
    data = repo[1]
    calls = []

    def run_agent(role, prompt, cwd, log_id, **_):
        calls.append((role, prompt))
        return subprocess.CompletedProcess([], 0, f"finding from {log_id}", "")

    def prompt(role, **k):
        return f"{role}\n{k.get('findings', '')}\n{k.get('paths', {})}"

    monkeypatch.setattr(bundle, "prompt", prompt)
    monkeypatch.setattr(launch, "run_agent", run_agent)
    assert sprint.cmd_sprint_review(ns("1")) == 0
    angles = sorted(p.stem for p in (config.plugin_root() / "angles").glob("*.md"))
    folder = data / "sprints" / "1"
    written = sorted(p.name for p in folder.glob("review-1.*.md"))
    assert written == [f"review-1.{a}.md" for a in angles] and len(calls) == len(angles) + 1
    assert {r for r, _ in calls[:-1]} == {"angle-reviewer"}
    role, text = calls[-1]
    assert role == "fixer" and all(f"reviewer-1-{a}" in text for a in angles)
    handback = folder / "handback-1.md"
    assert f"'HANDBACK_PATH': '{handback}'" in text
    out = capsys.readouterr().out
    assert all(str(folder / name) in out for name in written) and str(handback) in out


def test_review_failure_names_the_log(repo, monkeypatch, capsys):
    def run_agent(role, prompt, cwd, log_id, **_):
        return subprocess.CompletedProcess([], 1 if role == "fixer" else 0, "f", "see x")

    monkeypatch.setattr(bundle, "prompt", lambda role, **k: role)
    monkeypatch.setattr(launch, "run_agent", run_agent)
    assert sprint.cmd_sprint_review(ns("1")) == 1
    log = repo[1] / "logs" / "sprint-001-fixer-1.log"
    assert f"read {log}" in capsys.readouterr().out


def refused_land(capsys) -> str:
    with pytest.raises(SystemExit) as exit_:
        sprint.cmd_sprint_land(ns("1"))
    assert exit_.value.code == 2
    return capsys.readouterr().err


def test_land_refuses_in_progress_cards(repo, tmp_path, monkeypatch, capsys):
    gh = fake_gh(tmp_path, monkeypatch)
    repo[1].joinpath("plan.md").write_text(SLATE.format(status="in-progress"))
    assert "story-001 still in-progress" in refused_land(capsys)
    assert not gh.exists()


def test_land_refuses_a_failed_version_wall(repo, tmp_path, monkeypatch, capsys):
    gh = fake_gh(tmp_path, monkeypatch)
    commit(repo[0], {"CHANGELOG.md": "## 1.3.0\n"}, "changelog drifts")
    assert "version wall" in refused_land(capsys)
    assert not gh.exists() and not repo[2].exists()


def test_land_refuses_a_red_sprint_hook_before_the_pr(repo, tmp_path, monkeypatch, capsys):
    gh = fake_gh(tmp_path, monkeypatch)
    lefthook = tmp_path / "bin" / "lefthook"
    lefthook.write_text("#!/bin/sh\nexit 1\n")
    lefthook.chmod(0o755)
    commit(repo[0], {"lefthook.yml": "sprint:\n"}, "lefthook")
    assert "the sprint hook exited 1" in refused_land(capsys)
    assert not gh.exists() and not (repo[1] / "sprints" / "1" / "land.json").exists()


def test_versioning_off_releases_without_a_wall_or_a_tag(repo, tmp_path, monkeypatch, capsys):
    root, data, _ = repo
    gh = fake_gh(tmp_path, monkeypatch)
    off = "trunk: main\nversioning: off\nroles:\n  reviewer: claude/opus\n"
    commit(root, {".xp/config.yml": off, "CHANGELOG.md": "## v0.0.1 — stale on purpose\n"}, "off")
    assert sprint.cmd_sprint_land(ns("1")) == 0
    assert "--title Sprint 1 --body Sprint 1." in gh.read_text() and "v1.2.0" not in gh.read_text()
    merge_on_trunk(root)
    assert sprint.cmd_sprint_post_merge(ns("1")) == 0
    assert git(root, "tag", "--list") == "" and config.sprint_branch() == ""
    record = json.loads((data / "sprints" / "1" / "release.json").read_text())
    assert record["version"] == "" and record["tag"] == ""
    assert "versioning: off" in capsys.readouterr().out
