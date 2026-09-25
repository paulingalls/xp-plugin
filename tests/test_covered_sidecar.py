"""Covered Verify-red reviews leave the queue only after a successful land."""

import json

from close_free_card_cases import free_identity
from close_helpers import CLEAN, close, free, make_repo, marker, stub_reviewer
from test_close_free import reviewed


def superseded(tmp_path, *, red=True):
    repo, env, g = make_repo(tmp_path)
    stub_reviewer(tmp_path, report=CLEAN, exit_code=1)
    assert close(repo, env, "review").returncode == 2
    stub_reviewer(tmp_path)
    assert close(repo, env, "review").returncode == 0
    sidecar = tmp_path / "data/markers/story-042.round-2.launch"
    state = json.loads(sidecar.read_text())
    if red:
        state.update(verify_red="Verify red", verify_head=marker(tmp_path)["shown_sha"])
        sidecar.write_text(json.dumps(state))
    return repo, env, g, sidecar


def test_uncovered_red_sidecar_stays_queued(tmp_path):
    repo, env, g, sidecar = superseded(tmp_path)
    state = json.loads(sidecar.read_text())
    g("checkout", "-q", "main")
    (repo / "sibling").write_text("sibling\n")
    g("add", "sibling")
    g("commit", "-qm", "sibling")
    sibling = g("rev-parse", "HEAD").stdout.strip()
    g("checkout", "-q", "story-042-branch")
    state["verify_head"] = sibling
    sidecar.write_text(json.dumps(state))
    evidence = sidecar.read_bytes()

    refused = close(repo, env, "land")

    assert refused.returncode == 2 and "salvage" in refused.stderr
    assert sidecar.read_bytes() == evidence


def test_nonred_sidecar_stays_queued(tmp_path):
    repo, env, _g, sidecar = superseded(tmp_path, red=False)
    evidence = sidecar.read_bytes()

    refused = close(repo, env, "land")

    assert refused.returncode == 2 and "salvage" in refused.stderr
    assert sidecar.read_bytes() == evidence


def test_canonical_red_marker_stays_queued(tmp_path):
    repo, env, _g, sidecar = superseded(tmp_path)
    canonical = sidecar.with_name("story-042.review-launch")
    canonical.write_bytes(sidecar.read_bytes())
    evidence = canonical.read_bytes()

    refused = close(repo, env, "land")

    assert refused.returncode == 2 and "repair" in refused.stderr
    assert canonical.read_bytes() == evidence and sidecar.exists()


def test_dry_run_previews_without_moving(tmp_path):
    repo, env, _g, sidecar = superseded(tmp_path)
    evidence = sidecar.read_bytes()
    archived = tmp_path / "data/reports/story-042.COVERED-round-2.launch"

    preview = close(repo, env, "land", "--dry-run")

    assert preview.returncode == 0, preview.stderr
    assert f"would set aside {sidecar} -> {archived}; covered by round 1" in preview.stdout
    assert sidecar.read_bytes() == evidence and not archived.exists()


def test_dirty_tree_refuses_before_disposition(tmp_path):
    repo, env, _g, sidecar = superseded(tmp_path)
    evidence = sidecar.read_bytes()
    (repo / "src/thing.py").write_text("dirty\n")

    refused = close(repo, env, "land")

    assert refused.returncode == 2 and "dirty" in refused.stderr
    assert "set aside" not in refused.stdout
    assert sidecar.read_bytes() == evidence


def test_missing_plan_refuses_after_scan_without_disposition(tmp_path):
    repo, env, _g, sidecar = superseded(tmp_path)
    evidence = sidecar.read_bytes()
    (tmp_path / "data/plan.md").unlink()

    refused = close(repo, env, "land")

    assert refused.returncode == 2 and "no plan" in refused.stderr
    assert "set aside" not in refused.stdout
    assert sidecar.read_bytes() == evidence


def test_existing_archive_is_never_overwritten(tmp_path):
    repo, env, _g, sidecar = superseded(tmp_path)
    archived = tmp_path / "data/reports/story-042.COVERED-round-2.launch"
    archived.write_bytes(b"earlier evidence")
    evidence = sidecar.read_bytes()

    refused = close(repo, env, "land")

    assert refused.returncode == 2 and "already exists" in refused.stderr
    assert sidecar.read_bytes() == evidence and archived.read_bytes() == b"earlier evidence"


def test_unreadable_sidecar_refuses_without_disposition(tmp_path):
    repo, env, _g, sidecar = superseded(tmp_path)
    sidecar.write_text("{broken")

    refused = close(repo, env, "land")

    assert refused.returncode == 2 and "not readable" in refused.stderr
    assert sidecar.read_text() == "{broken"


def test_covering_round_must_be_latest_recorded_round(tmp_path):
    repo, env, _g, sidecar = superseded(tmp_path)
    evidence = sidecar.read_bytes()
    path = tmp_path / "data/markers/story-042.close.json"
    state = json.loads(path.read_text())
    state["rounds"][-1]["shown_sha"] = "different"
    path.write_text(json.dumps(state))

    refused = close(repo, env, "land")

    assert refused.returncode == 2 and "latest review round" in refused.stderr
    assert sidecar.read_bytes() == evidence


def free_superseded(tmp_path):
    repo, env, g = reviewed(tmp_path)
    _branch, key = free_identity(g)
    stub_reviewer(tmp_path, exit_code=1)
    assert free(repo, env, "fix-typo", "review").returncode == 2
    stub_reviewer(tmp_path)
    assert free(repo, env, "fix-typo", "review").returncode == 0
    sidecars = sorted((tmp_path / "data/markers").glob(f"{key}.round-*.launch"))
    assert sidecars
    sidecar = sidecars[-1]
    state = json.loads(sidecar.read_text())
    state.update(verify_red="Verify red", verify_head=marker(tmp_path, key)["shown_sha"])
    sidecar.write_text(json.dumps(state))
    return repo, env, sidecar


def test_free_land_disposes_covered_sidecar_after_opening_pr(tmp_path):
    repo, env, sidecar = free_superseded(tmp_path)
    evidence = sidecar.read_bytes()

    landed = free(repo, env, "fix-typo", "land")

    archived = tmp_path / "data/reports" / sidecar.name.replace(".round-", ".COVERED-round-")
    assert landed.returncode == 0, landed.stderr
    assert f"set aside {sidecar} -> {archived}" in landed.stdout
    assert not sidecar.exists() and archived.read_bytes() == evidence


def test_failed_pr_create_leaves_covered_sidecar_queued(tmp_path):
    repo, env, sidecar = free_superseded(tmp_path)
    evidence = sidecar.read_bytes()
    gh = tmp_path / "bin/gh"
    gh.write_text("#!/bin/sh\nexit 1\n")
    gh.chmod(0o755)

    refused = free(repo, env, "fix-typo", "land")

    assert refused.returncode != 0 and "pr create" in refused.stderr
    assert "set aside" not in refused.stdout
    assert sidecar.read_bytes() == evidence
