"""Land guards for version-only manifest motion and untagged releases."""

import json
import sys

import pytest
from close_helpers import PLUGIN, free, free_repo, gh_calls
from test_close_free import reviewed

sys.path.insert(0, str(PLUGIN / "scripts" / "close"))


def write_manifest(repo, g, version, **other):
    (repo / "plugin.json").write_text(json.dumps({"version": version, **other}) + "\n")
    g("add", "plugin.json")
    assert g("commit", "-qm", f"manifest {version}").returncode == 0


def branch_name(g):
    return g("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()


def test_second_free_release_can_land_after_version_only_trunk_motion(tmp_path):
    repo, env, g = reviewed(tmp_path)
    branch = branch_name(g)
    reviewed_base = g("merge-base", "main", branch).stdout.strip()
    g("checkout", "-q", "main")
    write_manifest(repo, g, "0.2.1")
    g("tag", "v0.2.1")
    g("push", "-q", "origin", "main")
    trunk = g("rev-parse", "main").stdout.strip()
    g("checkout", "-q", branch)
    assert g("merge", "--no-edit", "main").returncode == 0
    write_manifest(repo, g, "0.2.2")
    assert json.loads(g("show", f"{reviewed_base}:plugin.json").stdout) == {"version": "0.2.0"}
    assert json.loads(g("show", f"{trunk}:plugin.json").stdout) == {"version": "0.2.1"}
    landed = free(repo, env, "fix-typo", "land")
    assert landed.returncode == 0, landed.stderr
    assert len([c for c in gh_calls(tmp_path) if c[:2] == ["pr", "create"]]) == 1


def test_untagged_trunk_release_refuses_merged_leg_at_same_version(tmp_path):
    repo, env, g = reviewed(tmp_path)
    branch = branch_name(g)
    g("checkout", "-q", "main")
    write_manifest(repo, g, "0.2.1")
    (repo / "src" / "release.py").write_text("released = True\n")
    g("add", "-A")
    assert g("commit", "-qm", "first release merged without tag").returncode == 0
    g("push", "-q", "origin", "main")
    g("checkout", "-q", branch)
    assert g("merge", "--no-edit", "main").returncode == 0
    (repo / "src" / "second.py").write_text("second = True\n")
    g("add", "-A")
    assert g("commit", "-qm", "second release content").returncode == 0
    landed = free(repo, env, "fix-typo", "land")
    assert landed.returncode == 2
    assert "plugin.json" in landed.stderr and "0.2.1" in landed.stderr
    assert not gh_calls(tmp_path)


def advance_trunk(repo, g, branch, *, tag=False, dependency=None, source=None):
    g("checkout", "-q", "main")
    data = {"dependencies": {"left": dependency}} if dependency else {}
    write_manifest(repo, g, "0.2.1", **data)
    if source is not None:
        (repo / "src/free.py").write_text(source)
        g("add", "src/free.py")
        assert g("commit", "-qm", "shared source edit").returncode == 0
    if tag:
        g("tag", "v0.2.1")
    g("push", "-q", "origin", "main")
    g("checkout", "-q", branch)


def test_untagged_trunk_release_refuses_unmerged_leg_before_overlap(tmp_path):
    repo, env, g = reviewed(tmp_path)
    advance_trunk(repo, g, branch_name(g))
    landed = free(repo, env, "fix-typo", "land")
    assert landed.returncode == 2
    assert "trunk manifest plugin.json declares 0.2.1" in landed.stderr
    assert "Tag the trunk release" in landed.stderr
    assert "v0.2.2" in landed.stderr
    assert "overlaps" not in landed.stderr
    assert not gh_calls(tmp_path)


def test_leg_ahead_of_untagged_trunk_is_sent_to_tag_not_back(tmp_path):
    repo, env, g = reviewed(tmp_path)
    advance_trunk(repo, g, branch_name(g))
    write_manifest(repo, g, "0.2.2")
    landed = free(repo, env, "fix-typo", "land")
    assert landed.returncode == 2
    assert "Tag the trunk release" in landed.stderr


def test_tagged_trunk_release_refuses_behind_leg_on_version_wall(tmp_path):
    repo, env, g = reviewed(tmp_path)
    advance_trunk(repo, g, branch_name(g), tag=True)
    landed = free(repo, env, "fix-typo", "land")
    assert landed.returncode == 2
    assert "plugin.json" in landed.stderr and "v0.2.2" in landed.stderr
    assert "overlaps" not in landed.stderr


def test_dependency_edit_on_both_sides_still_overlaps(tmp_path):
    repo, env, g = reviewed(tmp_path)
    advance_trunk(repo, g, branch_name(g), tag=True, dependency="trunk")
    write_manifest(repo, g, "0.2.2", dependencies={"right": "leg"})
    landed = free(repo, env, "fix-typo", "land")
    assert landed.returncode == 2
    assert "overlaps" in landed.stderr and "plugin.json" in landed.stderr


def test_second_shared_file_is_the_only_overlap(tmp_path):
    repo, env, g = reviewed(tmp_path)
    advance_trunk(repo, g, branch_name(g), tag=True, source="B = 2\n")
    write_manifest(repo, g, "0.2.2")
    landed = free(repo, env, "fix-typo", "land")
    assert landed.returncode == 2
    assert "overlaps" in landed.stderr
    assert "src/free.py" in landed.stderr
    assert "plugin.json" not in landed.stderr


@pytest.mark.parametrize("dependency_side", ["trunk", "leg"])
def test_recorded_base_requires_version_only_on_each_side(tmp_path, dependency_side):
    repo, env, g = reviewed(tmp_path)
    on_trunk = dependency_side == "trunk"
    advance_trunk(repo, g, branch_name(g), tag=True, dependency="trunk" if on_trunk else None)
    assert g("merge", "--no-edit", "main").returncode == (1 if on_trunk else 0)
    if on_trunk:
        write_manifest(repo, g, "0.2.1", dependencies={"left": "trunk"})
    write_manifest(repo, g, "0.2.2", dependencies={"left": "trunk" if on_trunk else "leg"})
    landed = free(repo, env, "fix-typo", "land")
    assert landed.returncode == 2
    assert "trunk moved after the recorded round" in landed.stderr
    assert "plugin.json" in landed.stderr


def test_malformed_trunk_manifest_refuses_explicitly(tmp_path):
    repo, env, g = reviewed(tmp_path)
    branch = branch_name(g)
    g("checkout", "-q", "main")
    (repo / "plugin.json").write_text("{broken\n")
    g("commit", "-qam", "broken trunk manifest")
    g("push", "-q", "origin", "main")
    g("checkout", "-q", branch)
    landed = free(repo, env, "fix-typo", "land")
    assert landed.returncode == 2
    assert "trunk manifest plugin.json" in landed.stderr
    assert "readable MAJOR.MINOR.PATCH" in landed.stderr


def executable(path, body):
    path.write_text("#!/bin/sh\n" + body)
    path.chmod(0o755)
    return str(path)


def order_fixture(tmp_path, free_leg):
    from close_free_card_cases import add_free_card, checkout_free, commit_on_free, spawn_free
    from close_helpers import close, make_repo

    verify = tmp_path / "verify"
    tier = tmp_path / "tier"
    executable(verify, "exit 0\n")
    executable(tier, "exit 0\n")
    if free_leg:
        repo, env, g = free_repo(tmp_path)
        config = repo / ".xp/config.yml"
        config.write_text(config.read_text().replace("  story: true", f"  story: {tier}"))
        g("commit", "-qam", "configure tier")
        g("push", "-q", "origin", "main")
        assert free(repo, env, "fix-typo", "start").returncode == 0
        branch, key = checkout_free(g)
        commit_on_free(repo, g)
        add_free_card(env, key, str(verify))
        tree = spawn_free(repo, env, g, tmp_path, key)
        assert g("worktree", "remove", "--force", str(tree)).returncode == 0
        g("checkout", "-q", branch)
        assert free(repo, env, "fix-typo", "review").returncode == 0

        def land(*args):
            return free(repo, env, "fix-typo", "land", *args)
    else:
        repo, env, g = make_repo(tmp_path, verify=str(verify), files="src/thing.py, .xp/config.yml")
        config = repo / ".xp/config.yml"
        config.write_text(
            f"release: story\nroles:\n  reviewer: claude/opus\ntests:\n  story: {tier}\n"
        )
        g("commit", "-qam", "configure story tier")
        assert close(repo, env, "review").returncode == 0

        def land(*args):
            return close(repo, env, "land", *args)

    return land, verify, tier


@pytest.mark.parametrize("free_leg", [False, True], ids=["story", "free"])
def test_red_tier_stops_before_red_verify(tmp_path, free_leg):
    land, verify, tier = order_fixture(tmp_path, free_leg)
    (next((tmp_path / "data/markers").glob("*.verify.json"))).unlink()
    sentinel = tmp_path / "verify-ran"
    executable(tier, "exit 1\n")
    executable(verify, f"touch {sentinel}\nexit 1\n")
    result = land()
    assert result.returncode == 2
    assert "test tier red" in result.stderr
    assert not sentinel.exists()


@pytest.mark.parametrize("free_leg", [False, True], ids=["story", "free"])
def test_green_tier_still_runs_red_verify(tmp_path, free_leg):
    land, verify, tier = order_fixture(tmp_path, free_leg)
    (next((tmp_path / "data/markers").glob("*.verify.json"))).unlink()
    sentinel = tmp_path / "tier-ran"
    executable(tier, f"touch {sentinel}\nexit 0\n")
    executable(verify, "exit 1\n")
    result = land()
    assert result.returncode == 2
    assert sentinel.exists()
    assert "Verify red" in result.stderr


def test_story_preview_lists_tier_before_verify(tmp_path):
    land, verify, tier = order_fixture(tmp_path, False)
    preview = land("--dry-run")
    assert preview.returncode == 0, preview.stderr
    assert preview.stdout.index(f"would run: {tier}") < preview.stdout.index(f"would run: {verify}")


@pytest.mark.parametrize("mode", ["off", "none"])
def test_free_without_version_wall_keeps_manifest_overlap(tmp_path, mode):
    from close_free_card_cases import add_free_card, checkout_free, commit_on_free, spawn_free

    repo, env, g = free_repo(tmp_path)
    config = repo / ".xp/config.yml"
    if mode == "off":
        config.write_text(config.read_text() + "versioning: off\n")
    else:
        config.write_text(
            config.read_text().replace("version_files: plugin.json", "version_files: none")
        )
    g("commit", "-qam", "configure version mode")
    g("push", "-q", "origin", "main")
    assert free(repo, env, "fix-typo", "start").returncode == 0
    branch, key = checkout_free(g)
    commit_on_free(repo, g)
    add_free_card(env, key)
    tree = spawn_free(repo, env, g, tmp_path, key)
    assert g("worktree", "remove", "--force", str(tree)).returncode == 0
    g("checkout", "-q", branch)
    assert free(repo, env, "fix-typo", "review").returncode == 0
    advance_trunk(repo, g, branch)
    landed = free(repo, env, "fix-typo", "land")
    assert landed.returncode == 2
    assert "overlaps" in landed.stderr and "plugin.json" in landed.stderr


def test_carded_story_keeps_manifest_overlap(tmp_path):
    from close_helpers import close, make_repo

    repo, env, g = make_repo(tmp_path, files="src/thing.py, plugin.json")
    g("checkout", "-q", "main")
    config = repo / ".xp/config.yml"
    config.write_text("release: story\nversion_files: plugin.json\n" + config.read_text())
    g("add", ".xp/config.yml")
    assert g("commit", "-qm", "use story release mode").returncode == 0
    write_manifest(repo, g, "0.2.0")
    g("checkout", "-q", "story-042-branch")
    assert g("rebase", "main").returncode == 0
    write_manifest(repo, g, "0.2.1")
    assert close(repo, env, "review").returncode == 0
    g("checkout", "-q", "main")
    write_manifest(repo, g, "0.2.2")
    g("checkout", "-q", "story-042-branch")
    landed = close(repo, env, "land")
    assert landed.returncode == 2
    assert "overlaps" in landed.stderr and "plugin.json" in landed.stderr


def test_first_free_release_may_add_missing_trunk_manifest(tmp_path):
    from close_free_card_cases import add_free_card, checkout_free, commit_on_free, spawn_free

    repo, env, g = free_repo(tmp_path)
    (repo / "plugin.json").unlink()
    g("add", "-A")
    g("commit", "-qm", "remove trunk manifest")
    g("push", "-q", "origin", "main")
    assert free(repo, env, "fix-typo", "start").returncode == 0
    branch, key = checkout_free(g)
    commit_on_free(repo, g)
    write_manifest(repo, g, "0.2.1")
    add_free_card(env, key)
    tree = spawn_free(repo, env, g, tmp_path, key)
    assert g("worktree", "remove", "--force", str(tree)).returncode == 0
    g("checkout", "-q", branch)
    assert free(repo, env, "fix-typo", "review").returncode == 0
    landed = free(repo, env, "fix-typo", "land")
    assert landed.returncode == 0, landed.stderr
    assert [c for c in gh_calls(tmp_path) if c[:2] == ["pr", "create"]]


def test_review_time_verify_still_runs_without_tier(tmp_path):
    import overlap

    sentinel = tmp_path / "review-verify"
    verify = executable(tmp_path / "review-cmd", f"touch {sentinel}\nexit 1\n")
    red = overlap.run_checks([[verify]], None)
    assert "Verify red" in red
    assert sentinel.exists()


def test_sprint_receipt_path_keeps_verify_before_full_tier(tmp_path, monkeypatch):
    import subprocess

    import overlap
    import work

    tier_ran = tmp_path / "full-ran"
    tier = executable(tmp_path / "full-tier", f"touch {tier_ran}\nexit 1\n")
    verify = executable(tmp_path / "full-verify", "exit 1\n")
    monkeypatch.setattr(work, "config_block_value", lambda *_: tier)
    monkeypatch.setattr(
        overlap,
        "git",
        lambda *args, **kwargs: subprocess.CompletedProcess(args, 0, "tree-sha\n", ""),
    )
    red, receipt = overlap.gates("HEAD", [[verify]], "full", False, prior_receipt={})
    assert "Verify red" in red
    assert receipt is None
    assert not tier_ran.exists()


@pytest.mark.parametrize("dependency_side", ["trunk", "leg"])
def test_version_file_requires_version_only_on_each_side(tmp_path, dependency_side):
    repo, env, g = reviewed(tmp_path)
    advance_trunk(
        repo,
        g,
        branch_name(g),
        tag=True,
        dependency="trunk" if dependency_side == "trunk" else None,
    )
    other = {"dependencies": {"right": "leg"}} if dependency_side == "leg" else {}
    write_manifest(repo, g, "0.2.2", **other)
    landed = free(repo, env, "fix-typo", "land")
    assert landed.returncode == 2
    assert "overlaps" in landed.stderr and "plugin.json" in landed.stderr


def test_present_but_unreadable_trunk_blob_refuses(tmp_path, monkeypatch):
    import subprocess

    import release

    def broken_blob(*args, **_kwargs):
        if args[0] == "show":
            return subprocess.CompletedProcess(args, 1, "", "object read failed")
        assert args[:4] == ("ls-tree", "-r", "--name-only", "main")
        return subprocess.CompletedProcess(args, 0, "plugin.json\n", "")

    monkeypatch.setattr(release, "git", broken_blob)
    refused = release.trunk_version_refusal("main", "v0.2.1", ["plugin.json"])
    assert "plugin.json" in refused and "unreadable" in refused
