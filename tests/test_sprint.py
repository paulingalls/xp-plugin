import json
import subprocess

import pytest
import xp
from test_land import commit, fake_gh, git, make_project, manifest, ns
from xpcore import bundle, config, launch, release, sprint

HOOK = "#!/bin/sh\ntest -f trunk.txt || exit 1\necho ran >> {log}\n"
SLATE = "## Sprint 1 — s\n\n#### story-001 — a   [{status}]\nAcceptance: true\n"


@pytest.fixture
def repo(tmp_path, monkeypatch, request):
    identifier = getattr(request, "param", "1")
    branch = f"sprint-{identifier}"
    root, data = make_project(tmp_path, monkeypatch)
    (data / "plan.md").write_text(
        SLATE.format(status="done").replace("Sprint 1", f"Sprint {identifier}")
    )
    hooklog = tmp_path / "hook.log"
    git(root, "switch", "-qc", branch)
    assert xp.main(["sprint", "open", identifier]) == 0
    assert config.sprint_branch() == branch
    (root / ".githooks").mkdir()
    (root / ".githooks" / "sprint").write_text(HOOK.format(log=hooklog))
    (root / ".githooks" / "sprint").chmod(0o755)
    commit(root, manifest("1.2.0"), "sprint work")
    git(root, "switch", "-q", "main")
    commit(root, {"trunk.txt": "t\n"}, "trunk moved")
    git(root, "push", "-q", "origin", "main")
    git(root, "switch", "-q", branch)
    return root, data, hooklog


def merge_on_trunk(root, branch="sprint-1"):
    git(root, "switch", "-q", "main")
    git(root, "merge", "-q", "--no-ff", branch, "-m", "PR")


def test_open_refuses_off_branch_then_records(tmp_path, monkeypatch, capsys):
    root, data = make_project(tmp_path, monkeypatch)
    (data / "plan.md").write_text("## Sprint 2 — s\n")
    with pytest.raises(SystemExit) as exit_:
        sprint.cmd_sprint_open(ns("2"))
    assert exit_.value.code == 2 and "not sprint-2" in capsys.readouterr().err
    git(root, "switch", "-qc", "sprint-2")
    assert sprint.cmd_sprint_open(ns("2")) == 0
    assert config.sprint_branch() == "sprint-2"


@pytest.mark.parametrize("repo", ["auth-cleanup", "078", "78"], indirect=True)
def test_land_tests_the_trial_merge_and_post_merge_skips_that_tree(
    repo, tmp_path, monkeypatch, capsys
):
    root, data, hooklog = repo
    branch = git(root, "branch", "--show-current")
    identifier = branch.removeprefix("sprint-")
    folder = data / "sprints" / identifier
    gh = fake_gh(tmp_path, monkeypatch)
    monkeypatch.setattr(
        launch, "run_agent", lambda *a, **k: subprocess.CompletedProcess([], 0, "finding", "")
    )
    assert xp.main(["sprint", "review", identifier]) == 0
    assert list(folder.glob("review-1.*.md"))
    assert xp.main(["sprint", "land", identifier]) == 0
    assert hooklog.read_text() == "ran\n"
    assert f"--base main --head {branch} --title Sprint {identifier} --body " in gh.read_text()
    assert "v1.2.0" in gh.read_text() and "review-1.test-vacuity.md" in gh.read_text()
    assert json.loads((folder / "land.json").read_text())["tested_tree"]
    assert not (root / "trunk.txt").exists()
    git(root, "switch", "-q", "main")
    with pytest.raises(SystemExit):
        xp.main(["sprint", "post-merge", identifier])
    err = capsys.readouterr().err
    assert f"{branch} is not merged into main" in err and "squash- or rebase-merged" in err
    assert git(root, "tag", "--list", "v1.2.0") == "" and config.sprint_branch() == branch
    assert git(root, "branch", "--list", branch)
    merge_on_trunk(root, branch)
    assert xp.main(["sprint", "post-merge", identifier]) == 0
    assert hooklog.read_text() == "ran\n"
    assert git(root, "cat-file", "-t", "v1.2.0") == "tag"
    record = json.loads((folder / "release.json").read_text())
    assert record["version"] == "1.2.0" and record["sprint"] == identifier
    assert config.sprint_branch() == "" and git(root, "branch", "--list", branch) == ""


def test_land_trial_merges_the_fetched_origin_trunk(repo, tmp_path, monkeypatch):
    root, _, hooklog = repo
    fake_gh(tmp_path, monkeypatch)
    git(root, "branch", "-f", "main", "main~1")  # a sibling clone moved origin; this clone is stale
    assert sprint.cmd_sprint_land(ns("1")) == 0
    assert hooklog.read_text() == "ran\n"


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
    git(root, "merge", "-q", "--squash", "sprint-1")
    git(root, "commit", "-qm", "Sprint 1 (#1)")
    assert sprint.cmd_sprint_post_merge(ns("1")) == 0
    assert "squash-merged" in capsys.readouterr().out and hooklog.read_text() == "ran\n"
    assert git(root, "cat-file", "-t", "v1.2.0") == "tag"
    assert config.sprint_branch() == "" and git(root, "branch", "--list", "sprint-1") == ""


def test_post_merge_rerun_after_the_tag_finishes_without_tagging_again(repo, monkeypatch):
    root, data, _ = repo
    merge_on_trunk(root)
    (data / "sprints" / "1").mkdir(parents=True)
    tree = git(root, "rev-parse", "HEAD^{tree}")
    (data / "sprints" / "1" / "land.json").write_text(
        json.dumps({"tested_tree": tree, "version": "1.2.0"})
    )
    with monkeypatch.context() as m:
        m.setattr(release, "write_release_record", lambda *a: 1 / 0)
        with pytest.raises(ZeroDivisionError):
            sprint.cmd_sprint_post_merge(ns("1"))
    assert git(root, "tag", "--points-at", "HEAD") == "v1.2.0"
    assert config.sprint_branch() == "sprint-1"
    assert sprint.cmd_sprint_post_merge(ns("1")) == 0
    assert git(root, "tag", "--points-at", "HEAD") == "v1.2.0"
    assert json.loads((data / "sprints" / "1" / "release.json").read_text())["tag"] == "v1.2.0"
    assert config.sprint_branch() == "" and git(root, "branch", "--list", "sprint-1") == ""


@pytest.mark.parametrize("dry", [False, True])
def test_plan_refuses_invalid_acceptance_before_review(repo, monkeypatch, capsys, dry):
    data, calls = repo[1], []
    (data / "plan.md").write_text(
        SLATE.format(status="planned") + "#### x — broken   [planned]\nAcceptance: true '(a' (b)\n"
    )
    review = data / "sprints" / "1" / "slate-review.md"
    review.parent.mkdir(parents=True)
    review.write_text("previous review\n")
    monkeypatch.setattr(
        launch,
        "run_agent",
        lambda *a, **k: calls.append(a) or subprocess.CompletedProcess([], 0, "ok", ""),
    )
    with pytest.raises(SystemExit) as exit_:
        xp.main(["sprint", "plan", "1", *(["--dry-run"] if dry else [])])
    err = capsys.readouterr().err
    assert exit_.value.code == 2 and "x" in err and "syntax error" in err.lower()
    assert not calls and review.read_text() == "previous review\n"


def test_plan_names_the_branch_to_cut(repo, monkeypatch, capsys):
    marker = repo[0] / "marker"
    (repo[1] / "plan.md").write_text(
        SLATE.format(status="planned").replace(
            "Acceptance: true", f"Acceptance: printf '%s' '(a)' > {marker}"
        )
        + "#### no-line — missing Acceptance   [planned]\n"
        + "## Sprint 2 — later\n#### broken — later   [planned]\n"
        + "Acceptance: true '(a' (b)\n"
    )
    calls = []
    monkeypatch.setattr(
        launch,
        "run_agent",
        lambda role, *a, **k: (
            calls.append(role) or subprocess.CompletedProcess([], 0, "slate ok", "")
        ),
    )
    assert xp.main(["sprint", "plan", "1"]) == 0
    assert "`git switch -c sprint-1 main`" in capsys.readouterr().out
    assert calls == ["slate-reviewer"] and not marker.exists()


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
    log = repo[1] / "logs" / "sprint-1-fixer-1.log"
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


def test_post_merge_ignores_another_release_tag_at_head(repo, capsys):
    """A free patch tagged trunk's head; the sprint's own release still walls, hooks and tags."""
    root, data, hooklog = repo
    merge_on_trunk(root)
    git(root, "tag", "-a", "v1.1.1", "-m", "a free patch's tag")
    (data / "sprints" / "1").mkdir(parents=True)
    (data / "sprints" / "1" / "land.json").write_text(
        json.dumps({"tested_tree": "x", "version": "1.2.0"})
    )
    assert sprint.cmd_sprint_post_merge(ns("1")) == 0
    assert hooklog.read_text() == "ran\n"  # the tree differed from what land tested
    assert "v1.2.0" in git(root, "tag", "--points-at", "HEAD").split()
    assert json.loads((data / "sprints" / "1" / "release.json").read_text())["version"] == "1.2.0"
    assert "already marks" not in capsys.readouterr().out


@pytest.mark.parametrize("origin", [True, False])
@pytest.mark.parametrize("work", [True, False])
def test_review_reads_the_trunk_merge_base(tmp_path, monkeypatch, capsys, origin, work):
    root, data = make_project(tmp_path, monkeypatch)
    (data / "plan.md").write_text("## Sprint range — s\n")
    stale = git(root, "rev-parse", "main")
    git(root, "switch", "-qc", "sprint-range")
    if work:
        commit(root, {"sprint.txt": "own\n"}, "sprint work")
    git(root, "switch", "-q", "main")
    base = commit(root, {"trunk.txt": "peer\n"}, "peer work")
    git(root, "switch", "-q", "sprint-range")
    git(root, "merge", "-q", "--no-ff", "main", "-m", "backmerge")
    git(root, "switch", "-q", "main")
    latest = commit(root, {"peer-later.txt": "later\n"}, "later peer work")
    git(root, "push", "-q", "origin", "main")
    git(root, "switch", "-q", "sprint-range")
    if origin:
        git(root, "branch", "-f", "main", stale)
        git(root, "update-ref", "refs/remotes/origin/main", stale)
    else:
        git(root, "remote", "remove", "origin")
    local = git(root, "rev-parse", "main")
    calls = []

    def run_agent(role, prompt, *a, **k):
        calls.append((role, prompt))
        return subprocess.CompletedProcess([], 0, "no findings", "")

    monkeypatch.setattr(launch, "run_agent", run_agent)
    if not work:
        with pytest.raises(SystemExit) as exit_:
            xp.main(["sprint", "review", "range", "--dry-run"])
        assert exit_.value.code == 2
        assert f"no changes since {base}" in capsys.readouterr().err
    else:
        assert xp.main(["sprint", "review", "range", "--dry-run"]) == 0
        output = capsys.readouterr().out
        contaminated = git(root, "diff", "--name-only", "main..HEAD")
        assert f"{base}..sprint-range" in output, f"{output}\nold range files:\n{contaminated}"
    assert not calls and git(root, "rev-parse", "main") == local
    if origin:
        assert git(root, "rev-parse", "origin/main") == latest
    if not work:
        return
    if origin:
        git(root, "update-ref", "refs/remotes/origin/main", stale)
    assert xp.main(["sprint", "review", "range"]) == 0
    reviews = [prompt for role, prompt in calls if role == "angle-reviewer"]
    assert reviews
    for prompt in reviews:
        assert f"## Commit range {base}..HEAD" in prompt
        files = prompt.split("### Files\n")[1].split("===== Paths")[0]
        assert "sprint.txt" in files
        assert "trunk.txt" not in files and "peer-later.txt" not in files
    assert git(root, "rev-parse", "main") == local
    if origin:
        assert git(root, "rev-parse", "origin/main") == latest
