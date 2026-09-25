"""A remote trunk advance must not become a stale review fork point."""

import json
import os
import subprocess
import sys

import pytest
from close_helpers import CLOSE, close, free, launches, make_repo
from sprint_helpers import make_repo as sprint_repo
from sprint_helpers import sprint
from test_close_free import reviewed


def advance_origin(tmp_path, repo, env, g, *, add_remote=False, branch="main", diverged=False):
    if add_remote:
        publish_trunk(tmp_path, g, branch)
    peer = tmp_path / "peer"
    subprocess.run(["git", "clone", "-q", str(tmp_path / "origin.git"), str(peer)], check=True)
    if branch != "main":
        subprocess.run(["git", "-C", str(peer), "checkout", "-q", branch], check=True)
    (peer / "remote-only.txt").write_text("remote advance\n")
    penv = {
        **os.environ,
        "GIT_AUTHOR_NAME": "peer",
        "GIT_AUTHOR_EMAIL": "peer@example.com",
        "GIT_COMMITTER_NAME": "peer",
        "GIT_COMMITTER_EMAIL": "peer@example.com",
    }
    subprocess.run(["git", "-C", str(peer), "add", "-A"], check=True, env=penv)
    subprocess.run(["git", "-C", str(peer), "commit", "-qm", "advance"], check=True, env=penv)
    subprocess.run(
        ["git", "-C", str(peer), "push", "-q", "origin", f"HEAD:{branch}"], check=True, env=penv
    )
    assert g("fetch", "-q", "origin", branch).returncode == 0
    local = g("rev-parse", f"refs/heads/{branch}").stdout.strip()
    remote = g("rev-parse", f"refs/remotes/origin/{branch}").stdout.strip()
    assert local != remote
    if not diverged:
        assert g("merge-base", "--is-ancestor", local, remote).returncode == 0
    return remote


def local_advance(repo, g, branch):
    current = g("branch", "--show-current").stdout.strip()
    assert g("checkout", "-q", branch).returncode == 0
    (repo / "local-only.txt").write_text("local advance\n")
    assert g("add", "-A").returncode == 0
    assert g("commit", "-qm", "local advance").returncode == 0
    if current != branch:
        assert g("checkout", "-q", current).returncode == 0


def publish_trunk(tmp_path, g, branch="main"):
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", str(origin)], check=True)
    assert g("remote", "add", "origin", str(origin)).returncode == 0
    assert g("push", "-q", "origin", branch).returncode == 0


def configure_release(repo, g, mode):
    assert g("checkout", "-q", "main").returncode == 0
    config = repo / ".xp" / "config.yml"
    config.write_text(f"release: {mode}\n" + config.read_text())
    assert g("add", "-A").returncode == 0
    assert g("commit", "-qm", f"{mode} release mode").returncode == 0
    assert g("checkout", "-q", "story-042-branch").returncode == 0
    assert g("rebase", "main").returncode == 0


def assert_diverged(g, branch, local="1"):
    counts = g(
        "rev-list", "--left-right", "--count", f"refs/heads/{branch}...refs/remotes/origin/{branch}"
    )
    assert counts.returncode == 0
    assert counts.stdout.split() == [local, "1"]


def assert_diverged_refusal(result, tmp_path, before, branch, tree="", local="1 local-only commit"):
    assert result.returncode == 2, result.stderr + result.stdout
    counts = f"local {branch} has {local} and origin/{branch} has 1 origin-only commit"
    assert counts in result.stderr
    if tree:
        assert f"git -C {tree} merge origin/{branch}" in result.stderr
    else:
        assert "no checkout holds it" in result.stderr
        assert f"git checkout {branch}" in result.stderr
        assert f"git merge origin/{branch}" in result.stderr
    assert launches(tmp_path) == before


def assert_stale(result, repo, launches_before, tree=""):
    assert result.returncode == 2, result.stderr + result.stdout
    if tree:
        assert f"git -C {tree} merge --ff-only origin/main" in result.stderr
    else:
        assert "git fetch origin main:main" in result.stderr
    assert launches_before == launches(repo.parent)


@pytest.mark.parametrize("leg", ["review", "land"])
def test_story_refuses_stale_trunk_before_review_or_land(tmp_path, leg):
    repo, env, g = make_repo(tmp_path)
    if leg == "land":
        assert close(repo, env, "review").returncode == 0
    advance_origin(tmp_path, repo, env, g, add_remote=True)
    before = launches(tmp_path)
    assert_stale(close(repo, env, leg, *(["--dry-run"] if leg == "land" else [])), repo, before)


@pytest.mark.parametrize("leg", ["review", "land"])
def test_free_refuses_stale_trunk_after_remote_merge(tmp_path, leg):
    repo, env, g = reviewed(tmp_path)
    advance_origin(tmp_path, repo, env, g)
    assert g("merge", "-q", "--no-edit", "origin/main").returncode == 0
    before = launches(tmp_path)
    result = free(repo, env, "fix-typo", leg, *(["--dry-run"] if leg == "land" else []))
    assert_stale(result, repo, before)


def test_sprint_review_refuses_stale_trunk(tmp_path):
    repo, env, g = sprint_repo(tmp_path)
    advance_origin(tmp_path, repo, env, g, add_remote=True)
    before = launches(tmp_path)
    assert_stale(sprint(repo, env, "review"), repo, before)


def test_fail_keeps_refusal_after_buffered_stdout(tmp_path):
    output = tmp_path / "combined.txt"
    with output.open("w") as stream:
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "import sys; sys.path.insert(0, sys.argv[1]); "
                "from close import fail; print('before'); sys.exit(fail('refused: after'))",
                str(CLOSE.parent),
            ],
            stdout=stream,
            stderr=stream,
        )
    assert result.returncode == 2
    assert output.read_text().splitlines() == ["before", "refused: after"]


def test_refusal_names_held_trunk_checkout(tmp_path):
    repo, env, g = make_repo(tmp_path)
    trunk_tree = tmp_path / "trunk"
    assert g("worktree", "add", "-q", str(trunk_tree), "main").returncode == 0
    advance_origin(tmp_path, repo, env, g, add_remote=True)
    assert_stale(close(repo, env, "review"), repo, [], str(trunk_tree))


@pytest.mark.parametrize("leg", ["review", "land"])
def test_free_refuses_diverged_trunk_before_review_or_land(tmp_path, leg):
    repo, env, g = reviewed(tmp_path)
    marker_path = next((tmp_path / "data" / "markers").glob("*.close.json"))
    marker = marker_path.read_text()
    local_advance(repo, g, "main")
    advance_origin(tmp_path, repo, env, g, diverged=True)
    assert_diverged(g, "main")
    assert g("merge", "-q", "--no-edit", "origin/main").returncode == 0
    before = launches(tmp_path)
    result = free(repo, env, "fix-typo", leg, *(["--dry-run"] if leg == "land" else []))
    assert_diverged_refusal(result, tmp_path, before, "main")
    assert marker_path.read_text() == marker
    assert not (tmp_path / "data" / "closes.jsonl").exists()


@pytest.mark.parametrize("leg", ["review", "land"])
def test_story_refuses_diverged_trunk_before_review_or_land(tmp_path, leg):
    repo, env, g = make_repo(tmp_path)
    configure_release(repo, g, "story")
    if leg == "land":
        reviewed = close(repo, env, "review")
        assert reviewed.returncode == 0, reviewed.stderr
    marker_path = tmp_path / "data" / "markers" / "story-042.close.json"
    marker = marker_path.read_text() if marker_path.exists() else None
    publish_trunk(tmp_path, g)
    local_advance(repo, g, "main")
    advance_origin(tmp_path, repo, env, g, diverged=True)
    assert_diverged(g, "main")
    assert g("merge", "-q", "--no-edit", "origin/main").returncode == 0
    before = launches(tmp_path)
    result = close(repo, env, leg, *(["--dry-run"] if leg == "land" else []))
    assert_diverged_refusal(result, tmp_path, before, "main")
    assert (marker_path.read_text() if marker_path.exists() else None) == marker
    assert not (tmp_path / "data" / "closes.jsonl").exists()


def sprint_story_repo(tmp_path):
    repo, env, g = make_repo(tmp_path)
    configure_release(repo, g, "sprint")
    (tmp_path / "data" / "sprint_branch").write_text("sprint-002\n")
    assert g("branch", "sprint-002", "main").returncode == 0
    publish_trunk(tmp_path, g)
    assert g("push", "-q", "origin", "sprint-002").returncode == 0
    return repo, env, g


@pytest.mark.parametrize("leg", ["review", "land"])
def test_sprint_story_refuses_diverged_trunk(tmp_path, leg):
    repo, env, g = sprint_story_repo(tmp_path)
    if leg == "land":
        reviewed = close(repo, env, "review")
        assert reviewed.returncode == 0, reviewed.stderr
    marker_path = tmp_path / "data" / "markers" / "story-042.close.json"
    marker = marker_path.read_text() if marker_path.exists() else None
    local_advance(repo, g, "sprint-002")
    advance_origin(tmp_path, repo, env, g, branch="sprint-002", diverged=True)
    assert_diverged(g, "sprint-002")
    before = launches(tmp_path)
    head = g("rev-parse", "HEAD").stdout.strip()
    result = close(repo, env, leg)
    assert_diverged_refusal(result, tmp_path, before, "sprint-002")
    assert g("rev-parse", "HEAD").stdout.strip() == head
    assert (marker_path.read_text() if marker_path.exists() else None) == marker
    assert not (tmp_path / "data" / "closes.jsonl").exists()


def test_sprint_close_review_refuses_diverged_main(tmp_path):
    repo, env, g = sprint_repo(tmp_path)
    publish_trunk(tmp_path, g)
    local_advance(repo, g, "main")
    advance_origin(tmp_path, repo, env, g, diverged=True)
    assert_diverged(g, "main")
    before = launches(tmp_path)
    assert_diverged_refusal(sprint(repo, env, "review"), tmp_path, before, "main")


def test_diverged_refusal_names_held_trunk_checkout(tmp_path):
    repo, env, g = make_repo(tmp_path)
    publish_trunk(tmp_path, g)
    tree = tmp_path / "trunk"
    assert g("worktree", "add", "-q", str(tree), "main").returncode == 0
    for n in range(2):
        (tree / f"local-only-{n}.txt").write_text("local advance\n")
        assert g("-C", str(tree), "add", "-A").returncode == 0
        assert g("-C", str(tree), "commit", "-qm", "local advance").returncode == 0
    advance_origin(tmp_path, repo, env, g, diverged=True)
    assert_diverged(g, "main", "2")
    result = close(repo, env, "review")
    assert_diverged_refusal(result, tmp_path, [], "main", str(tree), "2 local-only commits")


@pytest.mark.parametrize("state", ["ahead", "behind"])
def test_sprint_story_trunk_topology(tmp_path, state):
    repo, env, g = sprint_story_repo(tmp_path)
    if state == "ahead":
        local_advance(repo, g, "sprint-002")
        assert g("rev-list", "--count", "origin/sprint-002..sprint-002").stdout.strip() == "1"
        result = close(repo, env, "review")
        assert result.returncode == 0, result.stderr
        assert len(launches(tmp_path)) == 1
    else:
        advance_origin(tmp_path, repo, env, g, branch="sprint-002")
        result = close(repo, env, "review")
        assert result.returncode == 2, result.stderr
        assert "git fetch origin sprint-002:sprint-002" in result.stderr
        assert launches(tmp_path) == []


@pytest.mark.parametrize("state", ["equal", "ahead", "no-remote"])
def test_review_keeps_non_stale_trunks_working(tmp_path, state):
    repo, env, g = make_repo(tmp_path)
    if state != "no-remote":
        publish_trunk(tmp_path, g)
    if state == "ahead":
        local_advance(repo, g, "main")
    result = close(repo, env, "review")
    assert result.returncode == 0, result.stderr
    assert len(launches(tmp_path)) == 1


def test_fast_forward_allows_land_on_pre_advance_round(tmp_path):
    repo, env, g = reviewed(tmp_path)
    marker_path = next((tmp_path / "data" / "markers").glob("*.close.json"))
    original_rounds = len(json.loads(marker_path.read_text())["rounds"])
    remote = advance_origin(tmp_path, repo, env, g)
    assert g("merge", "-q", "--no-edit", "origin/main").returncode == 0
    assert free(repo, env, "fix-typo", "land", "--dry-run").returncode == 2
    assert g("fetch", "origin", "main:main").returncode == 0
    assert g("rev-parse", "main").stdout.strip() == remote
    landed = free(repo, env, "fix-typo", "land", "--dry-run")
    assert landed.returncode == 0, landed.stderr
    assert len(json.loads(marker_path.read_text())["rounds"]) == original_rounds


def test_review_records_fresh_fork_point_after_fast_forward(tmp_path):
    repo, env, g = make_repo(tmp_path)
    remote = advance_origin(tmp_path, repo, env, g, add_remote=True)
    assert g("merge", "-q", "--no-edit", "origin/main").returncode == 0
    assert close(repo, env, "review").returncode == 2
    assert g("fetch", "origin", "main:main").returncode == 0
    reviewed = close(repo, env, "review")
    assert reviewed.returncode == 0, reviewed.stderr
    assert (
        json.loads(next((tmp_path / "data" / "markers").glob("*.close.json")).read_text())[
            "review_base"
        ]
        == g("merge-base", remote, "HEAD").stdout.strip()
    )


def test_missing_local_trunk_is_refused_with_its_fetch(tmp_path):
    repo, env, g = make_repo(tmp_path)
    publish_trunk(tmp_path, g)
    assert g("remote", "set-head", "origin", "main").returncode == 0
    assert g("branch", "-D", "main").returncode == 0
    assert_stale(close(repo, env, "review"), repo, [])
