"""Reviewed story work lost in a trunk conflict resolution is not trunk motion."""

import json

from close_helpers import CLEAN, close, make_repo, marker_file, stub_reviewer


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


def test_story_land_refuses_an_unresolvable_shown_tree_after_trunk_moved(tmp_path):
    repo, env, g = make_repo(tmp_path)
    stub_reviewer(tmp_path, report=CLEAN)
    assert close(repo, env, "review").returncode == 0
    g("checkout", "-q", "main")
    (repo / "peer.py").write_text("PEER = 1\n")
    g("add", "-A")
    g("commit", "-qm", "peer lands a disjoint file")
    g("checkout", "-q", "story-042-branch")
    g("merge", "-q", "--no-edit", "main")
    state = json.loads(marker_file(tmp_path).read_text())
    state["shown_sha"] = "0" * 40
    marker_file(tmp_path).write_text(json.dumps(state))
    landed = close(repo, env, "land")
    assert landed.returncode == 2 and "0" * 8 in landed.stderr, landed.stderr
    assert "Traceback" not in landed.stderr
