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


def advance_origin(tmp_path, repo, env, g, *, add_remote=False):
    origin = tmp_path / "origin.git"
    if add_remote:
        subprocess.run(["git", "init", "-q", "--bare", str(origin)], check=True)
        assert g("remote", "add", "origin", str(origin)).returncode == 0
        assert g("push", "-q", "origin", "main").returncode == 0
    else:
        origin = tmp_path / "origin.git"
    peer = tmp_path / "peer"
    subprocess.run(["git", "clone", "-q", str(origin), str(peer)], check=True)
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
    subprocess.run(["git", "-C", str(peer), "push", "-q", "origin", "main"], check=True, env=penv)
    assert g("fetch", "-q", "origin", "main").returncode == 0
    local = g("rev-parse", "refs/heads/main").stdout.strip()
    remote = g("rev-parse", "refs/remotes/origin/main").stdout.strip()
    assert local != remote
    assert g("merge-base", "--is-ancestor", local, remote).returncode == 0
    return remote


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
    script = CLOSE
    output = tmp_path / "combined.txt"
    with output.open("w") as stream:
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "import sys; sys.path.insert(0, sys.argv[1]); "
                "from close import fail; print('before'); sys.exit(fail('refused: after'))",
                str(script.parent),
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


@pytest.mark.parametrize("state", ["equal", "ahead", "no-remote"])
def test_review_keeps_non_stale_trunks_working(tmp_path, state):
    repo, env, g = make_repo(tmp_path)
    if state != "no-remote":
        origin = tmp_path / "origin.git"
        subprocess.run(["git", "init", "-q", "--bare", str(origin)], check=True)
        assert g("remote", "add", "origin", str(origin)).returncode == 0
        assert g("push", "-q", "origin", "main").returncode == 0
    if state == "ahead":
        assert g("checkout", "-q", "main").returncode == 0
        (repo / "local-only.txt").write_text("unpushed\n")
        assert g("add", "-A").returncode == 0
        assert g("commit", "-qm", "local advance").returncode == 0
        assert g("checkout", "-q", "story-042-branch").returncode == 0
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
