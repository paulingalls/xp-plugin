"""Reviewed story work lost in a trunk conflict resolution is not trunk motion."""

from close_helpers import CLEAN, close, make_repo, stub_reviewer


def test_story_take_theirs_discards_reviewed_work(tmp_path):
    repo, env, g = make_repo(tmp_path)
    stub_reviewer(tmp_path, report=CLEAN)
    reviewed = close(repo, env, "review")
    assert reviewed.returncode == 0, reviewed.stderr
    g("checkout", "-q", "main")
    (repo / "src" / "thing.py").write_text("A = 3\n")
    g("commit", "-qam", "peer changes same path")
    g("checkout", "-q", "story-042-branch")
    assert g("merge", "-q", "--no-edit", "main").returncode != 0
    g("checkout", "--theirs", "src/thing.py")
    g("add", "-A")
    g("commit", "-qm", "discard reviewed story work")
    landed = close(repo, env, "land")
    assert landed.returncode == 2 and "src/thing.py" in landed.stderr
