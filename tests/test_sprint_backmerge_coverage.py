"""Coverage of trunk motion after a completed sprint round."""

import json
import shlex
import shutil
import subprocess

from sprint_helpers import CONFIG, PLUGIN, bundles, head, make_repo, marker_path, sprint


def prepared(tmp_path):
    repo, env, g = make_repo(tmp_path, config=CONFIG.replace("manifest.json", "package.json"))
    g("checkout", "-q", "main")
    (repo / "package.json").write_text('{"version": "0.3.0"}\n')
    g("add", "-A")
    g("commit", "-qm", "package manifest")
    g("checkout", "-q", "sprint-002")
    g("merge", "-q", "--no-edit", "main")
    base = g("merge-base", "main", "HEAD").stdout.strip()
    shown = head(repo, env)
    path = marker_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "rounds": [
                    {
                        "fixed": [],
                        "blocking": [],
                        "noted": [],
                        "reviewed_head": shown,
                        "shown_sha": shown,
                        "review_base": base,
                    }
                ],
                "shown_sha": shown,
                "reviewed_head": shown,
            }
        )
    )
    return repo, env, g, base, shown


def test_disjoint_peer_backmerge_keeps_the_completed_round(tmp_path):
    repo, env, g, base, _shown = prepared(tmp_path)
    g("checkout", "-q", "main")
    (repo / "peer.py").write_text("PEER = 1\n")
    g("add", "-A")
    g("commit", "-qm", "peer free patch")
    today = head(repo, env)
    g("checkout", "-q", "sprint-002")
    assert g("merge", "-q", "--no-edit", "main").returncode == 0
    result = sprint(repo, env, "land", "--dry-run")
    assert result.returncode == 0, result.stderr
    assert "peer.py" in result.stdout and f"{base}..{today}" in result.stdout
    assert len(json.loads(marker_path(tmp_path).read_text())["rounds"]) == 1


def peer_merge(repo, g, path, content, *, theirs=False):
    g("checkout", "-q", "main")
    target = repo / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content)
    g("add", "-A")
    assert g("commit", "-qm", "peer free patch").returncode == 0
    g("checkout", "-q", "sprint-002")
    merged = g("merge", "-q", "--no-edit", "main")
    if theirs:
        assert merged.returncode != 0
        g("checkout", "--theirs", path)
        g("add", "-A")
        assert g("commit", "-qm", "take trunk version").returncode == 0
    else:
        assert merged.returncode == 0, merged.stderr


def test_lead_code_after_disjoint_backmerge_still_refuses(tmp_path):
    repo, env, g, _base, _shown = prepared(tmp_path)
    peer_merge(repo, g, "peer.py", "PEER = 1\n")
    (repo / "lead.py").write_text("LEAD = 1\n")
    g("add", "-A")
    g("commit", "-qm", "lead code")
    result = sprint(repo, env, "land", "--dry-run")
    assert result.returncode == 2 and "lead.py" in result.stderr
    assert "peer.py" in result.stdout


def test_trunk_path_changed_by_sprint_at_head_refuses(tmp_path):
    repo, env, g, _base, _shown = prepared(tmp_path)
    (repo / "shared.py").write_text("SPRINT = 1\n")
    g("add", "-A")
    g("commit", "-qm", "sprint changes shared path")
    peer_merge(repo, g, "shared.py", "PEER = 1\n", theirs=True)
    (repo / "shared.py").write_text("PEER = 1\nSPRINT = 1\n")
    g("commit", "-qam", "retain sprint work")
    result = sprint(repo, env, "land", "--dry-run")
    assert result.returncode == 2 and "shared.py" in result.stderr


def test_take_theirs_cannot_discard_reviewed_sprint_path(tmp_path):
    repo, env, g, _base, _shown = prepared(tmp_path)
    (repo / "src.py").write_text("A = 1\nB = 'SPRINT-ONLY-SENTINEL'\nREVIEWED = 1\n")
    g("commit", "-qam", "reviewed sprint change")
    path = marker_path(tmp_path)
    state = json.loads(path.read_text())
    state["shown_sha"] = state["reviewed_head"] = head(repo, env)
    state["rounds"][0]["shown_sha"] = state["rounds"][0]["reviewed_head"] = head(repo, env)
    path.write_text(json.dumps(state))
    peer_merge(repo, g, "src.py", "A = 1\nPEER = 1\n", theirs=True)
    result = sprint(repo, env, "land", "--dry-run")
    assert result.returncode == 2 and "src.py" in result.stderr


def test_trunk_brought_gate_file_refuses(tmp_path):
    repo, env, g, _base, _shown = prepared(tmp_path)
    peer_merge(repo, g, ".xp/system.md", "# changed gate\n")
    result = sprint(repo, env, "land", "--dry-run")
    assert result.returncode == 2 and ".xp/system.md" in result.stderr


def test_missing_round_base_keeps_old_refusal(tmp_path):
    repo, env, g, _base, _shown = prepared(tmp_path)
    path = marker_path(tmp_path)
    state = json.loads(path.read_text())
    del state["rounds"][0]["review_base"]
    path.write_text(json.dumps(state))
    peer_merge(repo, g, "peer.py", "PEER = 1\n")
    result = sprint(repo, env, "land", "--dry-run")
    assert result.returncode == 2 and "peer.py" in result.stderr


def test_unrelated_recorded_base_keeps_old_refusal(tmp_path):
    repo, env, g, _base, _shown = prepared(tmp_path)
    g("checkout", "-qb", "other", "main")
    (repo / "other.py").write_text("OTHER = 1\n")
    g("add", "-A")
    g("commit", "-qm", "other history")
    unrelated = head(repo, env)
    g("checkout", "-q", "sprint-002")
    path = marker_path(tmp_path)
    state = json.loads(path.read_text())
    state["rounds"][0]["review_base"] = unrelated
    path.write_text(json.dumps(state))
    peer_merge(repo, g, "peer.py", "PEER = 1\n")
    result = sprint(repo, env, "land", "--dry-run")
    assert result.returncode == 2 and "peer.py" in result.stderr


def test_unresolvable_recorded_base_refuses_without_traceback(tmp_path):
    repo, env, g, _base, _shown = prepared(tmp_path)
    path = marker_path(tmp_path)
    state = json.loads(path.read_text())
    state["rounds"][0]["review_base"] = "0" * 40
    path.write_text(json.dumps(state))
    peer_merge(repo, g, "peer.py", "PEER = 1\n")
    result = sprint(repo, env, "land", "--dry-run")
    assert result.returncode == 2 and "peer.py" in result.stderr
    assert "Traceback" not in result.stderr


def test_local_trunk_ahead_of_origin_is_not_released_trunk(tmp_path):
    repo, env, g, _base, _shown = prepared(tmp_path)
    origin = tmp_path / "origin.git"
    assert g("init", "-q", "--bare", str(origin)).returncode == 0
    assert g("remote", "add", "origin", str(origin)).returncode == 0
    assert g("push", "-q", "origin", "main").returncode == 0
    peer_merge(repo, g, "local_only.py", "LOCAL = 1\n")
    result = sprint(repo, env, "land", "--dry-run")
    assert result.returncode == 2 and "local_only.py" in result.stderr


def test_confirming_bundle_excludes_disjoint_trunk_paths(tmp_path):
    repo, env, g, base, _shown = prepared(tmp_path)
    peer_merge(repo, g, "peer.py", "PEER = 1\n")
    today = g("merge-base", "main", "HEAD").stdout.strip()
    (repo / "lead.py").write_text("LEAD = 1\n")
    g("add", "-A")
    g("commit", "-qm", "lead code")
    result = sprint(repo, env, "review")
    assert result.returncode == 0, result.stderr
    launched = bundles(tmp_path)
    assert launched
    delta = next(body for body in launched if "The delta since the last recorded round" in body)
    assert "lead.py" in delta and f"{base}..{today}" in delta
    assert "Excluded trunk-only paths" in delta
    summary = delta.split("Per-file changes (added, deleted, full path):\n", 1)[1]
    assert "peer.py" not in summary.split("\n\n##", 1)[0]
    command = next(
        line for line in delta.splitlines() if line.startswith("git diff ") and "<path>" not in line
    )
    diff = subprocess.run(shlex.split(command), cwd=repo, env=env, capture_output=True, text=True)
    assert diff.returncode == 0 and "lead.py" in diff.stdout and "peer.py" not in diff.stdout
    one_path = next(
        line for line in delta.splitlines() if line.startswith("git diff ") and "<path>" in line
    )
    excluded_diff = subprocess.run(
        shlex.split(one_path.replace("<path>", "peer.py")),
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
    )
    assert excluded_diff.returncode == 0 and not excluded_diff.stdout
    latest = json.loads(marker_path(tmp_path).read_text())["rounds"][-1]
    assert latest["review_base"] == today


def test_first_completed_round_records_launch_base(tmp_path):
    repo, env, g = make_repo(tmp_path)
    base = g("merge-base", "main", "HEAD").stdout.strip()
    result = sprint(repo, env, "review")
    assert result.returncode == 0, result.stderr
    state = json.loads(marker_path(tmp_path).read_text())
    assert state["rounds"][-1]["review_base"] == base


def test_stale_local_trunk_refuses_before_exemption(tmp_path):
    repo, env, g, _base, _shown = prepared(tmp_path)
    origin = tmp_path / "origin.git"
    assert g("init", "-q", "--bare", str(origin)).returncode == 0
    assert g("remote", "add", "origin", str(origin)).returncode == 0
    assert g("push", "-q", "origin", "main").returncode == 0
    peer_merge(repo, g, "peer.py", "PEER = 1\n")
    assert g("push", "-q", "origin", "main").returncode == 0
    old = g("rev-parse", "main~1").stdout.strip()
    assert g("branch", "-f", "main", old).returncode == 0
    result = sprint(repo, env, "land", "--dry-run")
    assert result.returncode == 2 and "behind origin/main" in result.stderr


def test_diverged_local_trunk_refuses_before_exemption(tmp_path):
    repo, env, g, _base, _shown = prepared(tmp_path)
    origin = tmp_path / "origin.git"
    assert g("init", "-q", "--bare", str(origin)).returncode == 0
    assert g("remote", "add", "origin", str(origin)).returncode == 0
    assert g("push", "-q", "origin", "main").returncode == 0
    peer_merge(repo, g, "peer.py", "PEER = 1\n")
    assert g("push", "-q", "origin", "main").returncode == 0
    old = g("rev-parse", "main~1").stdout.strip()
    assert g("branch", "-f", "main", old).returncode == 0
    g("checkout", "-q", "main")
    (repo / "local.py").write_text("LOCAL = 1\n")
    g("add", "-A")
    g("commit", "-qm", "local divergence")
    g("checkout", "-q", "sprint-002")
    result = sprint(repo, env, "land", "--dry-run")
    assert result.returncode == 2 and "reconcile" in result.stderr


def test_bound_clearance_does_not_take_backmerge_exemption(tmp_path):
    repo, env, g, _base, _shown = prepared(tmp_path)
    path = marker_path(tmp_path)
    state = json.loads(path.read_text())
    state["rounds"][0].update(blocking=["GATE-ME"], clearable_by_full=["GATE-ME"])
    path.write_text(json.dumps(state))
    peer_merge(repo, g, "peer.py", "PEER = 1\n")
    result = sprint(repo, env, "land", "--dry-run")
    assert result.returncode == 2 and "peer.py" in result.stderr
    assert "trunk-only paths" not in result.stdout


def test_installed_shape_consumer_review_backmerge_land(tmp_path):
    repo, env, g = make_repo(tmp_path, config=CONFIG.replace("manifest.json", "package.json"))
    g("checkout", "-q", "main")
    (repo / "package.json").write_text('{"version": "0.2.0"}\n')
    g("add", "-A")
    g("commit", "-qm", "package manifest")
    g("checkout", "-q", "sprint-002")
    assert g("merge", "-q", "--no-edit", "main").returncode == 0
    (repo / "package.json").write_text('{"version": "0.3.0"}\n')
    g("commit", "-qam", "sprint release bump")
    installed = tmp_path / "installed" / "xp-plugin"
    shutil.copytree(PLUGIN, installed)
    close = installed / "scripts" / "close.py"
    reviewed = sprint(repo, env, "review", close=close)
    assert reviewed.returncode == 0, reviewed.stderr
    recorded = json.loads(marker_path(tmp_path).read_text())["rounds"][-1]["review_base"]
    g("checkout", "-q", "main")
    (repo / "package.json").write_text('{"version": "0.2.1"}\n')
    (repo / "peer.py").write_text("PEER = 1\n")
    g("add", "-A")
    g("commit", "-qm", "peer free patch release")
    g("checkout", "-q", "sprint-002")
    assert g("merge", "-q", "--no-edit", "main").returncode != 0
    g("checkout", "--ours", "package.json")
    g("add", "-A")
    assert g("commit", "-qm", "keep sprint release version").returncode == 0
    landed = sprint(repo, env, "land", "--dry-run", close=close)
    assert landed.returncode == 0, landed.stderr
    assert "peer.py" in landed.stdout and recorded in landed.stdout
