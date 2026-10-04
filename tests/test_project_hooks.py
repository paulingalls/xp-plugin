import json
from pathlib import Path

import pytest
import xp
from test_land import commit, fake_gh, git, make_project, manifest
from test_story import repo as story_repo
from xpcore import cards, config

repo = story_repo


def command(root, key, line):
    path = root / ".xp/config.yml"
    text = path.read_text()
    text = "\n".join(ln for ln in text.splitlines() if not ln.startswith(key + ":"))
    commit(root, {".xp/config.yml": text + f"\n{key}: {line}\n"}, key)


def entry(data, free):
    if not free:
        return ["story", "story-001"], "story-001", "story-001-add-the-widget", "sprint-001"
    assert xp.main(["free", "fix"]) == 0
    with (data / "plan.md").open("a") as out:
        out.write("Files: a.py\nAcceptance: true\n")
    return ["free", "fix"], "free-fix", "free-fix", "main"


def setup_config(root, base, line):
    command(root, "worktree_setup", line)
    if base != "main":
        git(root, "switch", "-q", base)
        git(root, "merge", "-q", "main")
        git(root, "switch", "-q", "main")


@pytest.mark.parametrize("free", [False, True])
def test_setup_precedes_agents_and_runs_once(repo, free):
    root = Path.cwd()
    args, identity, _, base = entry(repo, free)
    trace = repo / "setup"
    commit(root, {".gitignore": "bootstrap\n"}, "ignore build output")
    setup_config(root, base, f"pwd >> {trace}; touch bootstrap")
    harness = repo.parent / "bin/claude"
    harness.write_text(
        harness.read_text().replace(
            "prompt = sys.stdin.read()",
            f"assert open({str(trace)!r}).read().splitlines() == [os.getcwd()]\n"
            'assert os.path.isfile("bootstrap")\nprompt = sys.stdin.read()',
        )
    )
    assert xp.main(args) == 0
    assert (repo / "roles.txt").read_text().splitlines()[0] == ("executor" if free else "planner")
    assert xp.main(args) == 0
    assert trace.read_text().splitlines() == [str(repo / "worktrees" / identity)]


@pytest.mark.parametrize("free", [False, True])
def test_setup_failure_rolls_back_and_retries(repo, free, capsys):
    root = Path.cwd()
    args, identity, branch, base = entry(repo, free)
    line = f"pwd >> {repo / 'setup'}; touch untracked; exit 23"
    setup_config(root, base, line)
    with pytest.raises(SystemExit) as exc:
        xp.main(args)
    err = capsys.readouterr().err
    assert exc.value.code == 2 and line in err and "23" in err and "again" in err
    wt = repo / "worktrees" / identity
    assert not wt.exists() and not git(root, "branch", "--list", branch)
    assert str(wt) not in git(root, "worktree", "list", "--porcelain")
    assert not (repo / "roles.txt").exists()
    setup_config(root, base, f"pwd >> {repo / 'setup'}")
    assert xp.main(args) == 0
    assert wt.is_dir() and (repo / "stories" / identity / "review-1.md").is_file()


def test_setup_rollback_preserves_a_reused_branch_tip(repo):
    root = Path.cwd()
    args, identity, branch, base = entry(repo, False)
    setup_config(root, base, "exit 23")
    git(root, "switch", "-qc", branch, base)
    tip = commit(root, {"saved": "commits must survive\n"}, "saved work")
    git(root, "switch", "-q", "main")
    with pytest.raises(SystemExit):
        xp.main(args)
    assert git(root, "rev-parse", branch) == tip
    assert not (repo / "worktrees" / identity).exists()


@pytest.mark.parametrize("free", [False, True])
@pytest.mark.parametrize("status", [0, 24])
def test_teardown_runs_before_removal_even_when_red(tmp_path, monkeypatch, capsys, free, status):
    root, data = make_project(
        tmp_path, monkeypatch, "trunk: main\nversioning: on\nversion_files: package.json\n"
    )
    trace = data / "teardown"
    line = f"test -f bootstrap || exit 99; pwd >> {trace}; exit {status}"
    command(root, "worktree_teardown", line)
    command(
        root, "lifecycle_command", f"echo called >> {data / 'lifecycle'}; exit 25" if free else ""
    )
    commit(root, {".gitignore": "bootstrap\n"}, "ignore output")
    identity = "free-fix" if free else "story-001"
    (data / "plan.md").write_text(f"#### {identity} — fix   [in-progress]\nAcceptance: true\n")
    if not free:
        git(root, "switch", "-qc", "sprint-001")
        (data / "sprint_branch").write_text("sprint-001\n")
    wt = data / "worktrees" / identity
    branch = identity + "-work"
    git(root, "worktree", "add", "-q", "-b", branch, str(wt))
    tip = commit(wt, manifest("1.1.1"), "fix")
    (wt / "bootstrap").touch()
    if free:
        fake_gh(tmp_path, monkeypatch)
        assert xp.main(["free", "land", "fix"]) == 0
        assert wt.exists() and not trace.exists()
        git(root, "merge", "-q", "--no-ff", branch, "-m", "PR")
        assert xp.main(["free", "post-merge", "fix"]) == 0
        assert git(root, "cat-file", "-t", "v1.1.1") == "tag"
        assert not (data / "lifecycle").exists()
    else:
        assert xp.main(["story", "land", identity]) == 0
    assert trace.read_text().splitlines() == [str(wt)]
    assert not wt.exists() and not git(root, "branch", "--list", branch)
    assert git(root, "rev-parse", "HEAD^2") == tip
    assert cards.find_card(identity).status == "done"
    assert json.loads((data / "landed.jsonl").read_text())["id"] == identity
    if status:
        out = capsys.readouterr().out
        assert "warning:" in out and line in out and "24" in out


def lifecycle(root, data, guard, status):
    script = (
        "set -e\n"
        + guard
        + f'\nprintf "%s\\n" "$PWD" "$#" "$@" >> {data / "events"}\nexit {status}\n'
    )
    commit(root, {"lifecycle.sh": script}, "lifecycle script")
    command(root, "lifecycle_command", "sh lifecycle.sh")


@pytest.mark.parametrize("status", [0, 25])
def test_sprint_open_event_precedes_record_and_red_retries(tmp_path, monkeypatch, capsys, status):
    root, data = make_project(tmp_path, monkeypatch)
    (data / "plan.md").write_text("## Sprint 2 — s\n")
    lifecycle(root, data, f"test ! -f {data / 'sprint_branch'}", status)
    git(root, "switch", "-qc", "sprint-002")
    if status:
        with pytest.raises(SystemExit) as exc:
            xp.main(["sprint", "open", "002"])
        err = capsys.readouterr().err
        assert (
            exc.value.code == 2
            and "sprint-open" in err
            and "sh lifecycle.sh" in err
            and "25" in err
        )
        assert not config.sprint_branch()
        commit(
            root,
            {"lifecycle.sh": (root / "lifecycle.sh").read_text().replace("exit 25", "exit 0")},
            "fix lifecycle",
        )
    assert xp.main(["sprint", "open", "002"]) == 0
    assert (data / "events").read_text().splitlines() == [str(root), "2", "sprint-open", "002"] * (
        2 if status else 1
    )
    assert config.sprint_branch() == "sprint-002"


@pytest.mark.parametrize("status", [0, 25])
def test_story_close_after_acceptance_before_merge(tmp_path, monkeypatch, capsys, status):
    root, data = make_project(tmp_path, monkeypatch)
    lifecycle(root, data, 'test "$(git rev-parse sprint-001)" = "$(cat target)"', status)
    git(root, "switch", "-qc", "sprint-001")
    before = git(root, "rev-parse", "HEAD")
    (data / "sprint_branch").write_text("sprint-001\n")
    (data / "plan.md").write_text(
        f"#### story-001 — fix   [in-progress]\nAcceptance: echo acceptance >> {data / 'events'}\n"
    )
    wt = data / "worktrees/story-001"
    git(root, "worktree", "add", "-q", "-b", "story-001-work", str(wt))
    commit(wt, {"target": before}, "story work")
    if status:
        with pytest.raises(SystemExit):
            xp.main(["story", "land", "story-001"])
        err = capsys.readouterr().err
        assert "story-close" in err and "sh lifecycle.sh" in err and "25" in err
        assert git(root, "rev-parse", "HEAD") == before and wt.exists()
        assert cards.find_card("story-001").status == "in-progress"
        assert not (data / "landed.jsonl").exists()
        commit(
            wt,
            {"lifecycle.sh": (wt / "lifecycle.sh").read_text().replace("exit 25", "exit 0")},
            "fix lifecycle",
        )
    assert xp.main(["story", "land", "story-001"]) == 0
    assert (data / "events").read_text().splitlines() == [
        "acceptance",
        str(wt),
        "2",
        "story-close",
        "story-001",
    ] * (2 if status else 1)
    assert not wt.exists() and cards.find_card("story-001").status == "done"


@pytest.mark.parametrize("status", [0, 25])
def test_sprint_close_before_tag_and_record(tmp_path, monkeypatch, capsys, status):
    root, data = make_project(
        tmp_path,
        monkeypatch,
        "trunk: main\nversioning: off\n"
        if status
        else "trunk: main\nversioning: on\nversion_files: package.json\n",
    )
    (data / "plan.md").write_text("## Sprint 1 — s\n")
    guard = f'test ! -f {data / "sprints/1/release.json"}\ntest -z "$(git tag --list v1.2.0)"'
    lifecycle(root, data, guard, status)
    git(root, "switch", "-qc", "sprint-001")
    (data / "sprint_branch").write_text("sprint-001\n")
    hook = root / ".githooks/sprint"
    hook.parent.mkdir()
    hook.write_text("#!/bin/sh\nexit 0\n")
    hook.chmod(0o755)
    commit(root, manifest("1.2.0"), "sprint work")
    fake_gh(tmp_path, monkeypatch)
    assert xp.main(["sprint", "land", "001"]) == 0
    git(root, "switch", "-q", "main")
    git(root, "merge", "-q", "--no-ff", "sprint-001", "-m", "PR")
    if status:
        with pytest.raises(SystemExit):
            xp.main(["sprint", "post-merge", "001"])
        err = capsys.readouterr().err
        assert "sprint-close" in err and "sh lifecycle.sh" in err and "25" in err
        assert config.sprint_branch() == "sprint-001" and git(
            root, "branch", "--list", "sprint-001"
        )
        assert not (data / "sprints/1/release.json").exists() and not git(root, "tag", "--list")
        commit(
            root,
            {"lifecycle.sh": (root / "lifecycle.sh").read_text().replace("exit 25", "exit 0")},
            "fix lifecycle",
        )
    assert xp.main(["sprint", "post-merge", "001"]) == 0
    assert (data / "events").read_text().splitlines() == [str(root), "2", "sprint-close", "001"] * (
        2 if status else 1
    )
    assert not config.sprint_branch() and not git(root, "branch", "--list", "sprint-001")
    assert (data / "sprints/1/release.json").is_file()
    if not status:
        assert git(root, "cat-file", "-t", "v1.2.0") == "tag"
