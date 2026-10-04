import subprocess

import pytest
from xpcore import gitx


def sh(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def commit(cwd, name, text, message):
    (cwd / name).write_text(text)
    sh(cwd, "add", "-A")
    sh(cwd, "commit", "-qm", message)


@pytest.fixture
def repo(tmp_path):
    path = tmp_path / "repo"
    path.mkdir()
    sh(path, "init", "-q", "-b", "main")
    sh(path, "config", "user.email", "t@example.com")
    sh(path, "config", "user.name", "t")
    commit(path, "a.txt", "one\n", "init")
    return path


def test_git_error_names_the_command(repo):
    with pytest.raises(gitx.GitError, match="git rev-parse no-such-ref"):
        gitx.git("rev-parse", "no-such-ref", cwd=repo)
    assert gitx.git("rev-parse", "no-such-ref", cwd=repo, check=False) == "no-such-ref"


def test_basic_queries(repo):
    assert len(gitx.head(repo)) == 40
    assert gitx.current_branch(repo) == "main"
    assert gitx.branch_exists("main", repo) and not gitx.branch_exists("nope", repo)
    assert gitx.ref_exists("HEAD", repo) and not gitx.ref_exists("nope", repo)
    assert not gitx.is_dirty(repo)
    (repo / "new.txt").write_text("x")
    assert gitx.is_dirty(repo) and not gitx.is_dirty(repo, untracked=False)
    (repo / "a.txt").write_text("changed\n")
    assert gitx.git("status", "--porcelain", "--untracked-files=no", cwd=repo) == " M a.txt"


def test_fork_point_and_ranges(repo):
    base = gitx.head(repo)
    sh(repo, "switch", "-qc", "story")
    commit(repo, "b.txt", "two\n", "add b")
    sh(repo, "switch", "-q", "main")
    commit(repo, "c.txt", "three\n", "add c")
    assert gitx.fork_point("story", "main", repo) == base
    assert gitx.log_range(base, "story", repo).endswith(" add b")
    assert "+two" in gitx.diff_range(base, "story", repo)
    assert gitx.changed_files(base, "story", repo) == ["b.txt"]


def test_clean_trial_merge_then_abort(repo):
    sh(repo, "switch", "-qc", "story")
    commit(repo, "b.txt", "two\n", "add b")
    sh(repo, "switch", "-q", "main")
    commit(repo, "c.txt", "three\n", "add c")
    before = gitx.head(repo)
    try:
        assert gitx.trial_merge(repo, "story") == ""
        assert (repo / "b.txt").exists()
    finally:
        gitx.abort_merge(repo)
    assert gitx.head(repo) == before and not gitx.is_dirty(repo)
    assert not (repo / "b.txt").exists()


def test_conflicting_trial_merge_reports_and_abort_restores(repo):
    sh(repo, "switch", "-qc", "story")
    commit(repo, "a.txt", "story side\n", "story edit")
    sh(repo, "switch", "-q", "main")
    commit(repo, "a.txt", "main side\n", "main edit")
    before = gitx.head(repo)
    try:
        conflict = gitx.trial_merge(repo, "story")
        assert "CONFLICT" in conflict and "conflicted files:\na.txt" in conflict
    finally:
        gitx.abort_merge(repo)
    assert gitx.head(repo) == before and not gitx.is_dirty(repo)
    assert (repo / "a.txt").read_text() == "main side\n"
    gitx.abort_merge(repo)


def test_worktree_add_and_remove(repo, tmp_path):
    tree = tmp_path / "data" / "worktrees" / "story-001"
    gitx.worktree_add(tree, "story-001-x", "main", cwd=repo)
    assert gitx.current_branch(tree) == "story-001-x"
    assert gitx.common_dir(tree) == (repo / ".git").resolve()
    (tree / "build.log").write_text("ignored output")
    gitx.worktree_remove(tree, cwd=repo)
    assert not tree.exists() and gitx.branch_exists("story-001-x", repo)
    gitx.worktree_add(tree, "story-001-x", "main", cwd=repo)
    assert gitx.current_branch(tree) == "story-001-x"
