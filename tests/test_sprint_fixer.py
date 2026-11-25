import subprocess

import pytest
import xp
from test_land import commit, git, make_project
from xpcore import launch


@pytest.fixture
def repo(tmp_path, monkeypatch):
    root, data = make_project(tmp_path, monkeypatch)
    (data / "plan.md").write_text(
        "## Sprint 1 — s\n\n#### story-001 — a   [done]\nAcceptance: true\n"
    )
    git(root, "switch", "-qc", "sprint-1")
    commit(root, {"changed.txt": "sprint work\n"}, "sprint work")
    return root, data


@pytest.mark.parametrize(("filename", "returncode"), [("changed.txt", 1), ("untracked.txt", 0)])
def test_review_refuses_fixer_leftovers(repo, monkeypatch, capsys, filename, returncode):
    root, data = repo

    def run_agent(role, prompt, cwd, log_id):
        if role == "fixer":
            (cwd / filename).write_text("unfinished fix\n")
        return subprocess.CompletedProcess([], returncode if role == "fixer" else 0, "f", "")

    monkeypatch.setattr(launch, "run_agent", run_agent)
    with pytest.raises(SystemExit) as exit_:
        xp.main(["sprint", "review", "1"])
    assert exit_.value.code == 2
    output = capsys.readouterr()
    assert f"the fixer left uncommitted changes in {root}" in output.err
    assert f"git -C {root} status" in output.err
    assert str(data / "logs" / "sprint-1-fixer-1.log") in output.err
    assert "xp.py sprint land 1" in output.err
    assert "fixer done" not in output.out
    assert (root / filename).read_text() == "unfinished fix\n"


def test_review_lists_only_this_fixers_commits(repo, monkeypatch, capsys):
    root, _ = repo
    expected, excluded = [], [git(root, "log", "-1", "--format=%h %s")]

    def run_agent(role, prompt, cwd, log_id):
        if log_id == "sprint-1-reviewer-1-security":
            commit(cwd, {"reviewer.txt": "reviewer\n"}, "reviewer change")
            excluded.append(git(cwd, "log", "-1", "--format=%h %s"))
        if role == "fixer":
            for subject in ["first fix", "second fix"]:
                commit(cwd, {"changed.txt": subject}, subject)
                expected.append(git(cwd, "log", "-1", "--format=%h %s"))
        return subprocess.CompletedProcess([], 0, "f", "")

    monkeypatch.setattr(launch, "run_agent", run_agent)
    assert xp.main(["sprint", "review", "1"]) == 0
    output = capsys.readouterr().out
    assert len(excluded) == 2
    listed = output.split("fixer commits:\n", 1)[1].split("fixer done", 1)[0].splitlines()
    assert listed == list(reversed(expected))
    for line in expected:
        assert output.count(line) == 1
        assert output.index(line) < output.index("xp.py sprint land 1")
    assert all(line not in output for line in excluded)


def test_review_failure_names_the_log(repo, monkeypatch, capsys):
    def run_agent(role, prompt, cwd, log_id):
        return subprocess.CompletedProcess([], 1 if role == "fixer" else 0, "f", "see x")

    monkeypatch.setattr(launch, "run_agent", run_agent)
    assert xp.main(["sprint", "review", "1"]) == 1
    output = capsys.readouterr().out
    assert f"read {repo[1] / 'logs' / 'sprint-1-fixer-1.log'}" in output
    assert "xp.py sprint land" not in output
