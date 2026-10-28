import json

import pytest
import xp
from test_land import commit, fake_gh, free_patch, git, manifest, ns
from xpcore import cards, land, release


def park_lead(root):
    git(root, "switch", "-qc", "busy")
    commit(root, {"own": "own\n"}, "other branch")
    (root / "package.json").write_text("dirty manifest\n")
    git(root, "add", "package.json")
    (root / "package.json").write_text("unstaged manifest\n")
    (root / "untracked").write_text("keep\n")
    return lead_state(root)


def lead_state(root):
    return (
        git(root, "rev-parse", "HEAD"),
        git(root, "branch", "--show-current"),
        git(root, "diff", "--cached"),
        git(root, "diff"),
        (root / "untracked").read_bytes(),
        git(root, "status", "--porcelain"),
    )


def publish_merge(root, squash=False):
    git(
        root,
        "merge",
        "-q",
        "--squash" if squash else "--no-ff",
        "free-fix-x",
        *([] if squash else ["-m", "PR"]),
    )
    if squash:
        git(root, "commit", "-qm", "squashed PR")
    sha = git(root, "rev-parse", "HEAD")
    git(root, "push", "-q", "origin", "main")
    return sha


def test_free_post_merge_releases_tested_merge_off_dirty_lead(tmp_path, monkeypatch, capsys):
    fake_gh(tmp_path, monkeypatch)
    trace = tmp_path / "runs"
    root, data, wt = free_patch(tmp_path, monkeypatch, f"echo run >> {trace}")
    stale = git(root, "rev-parse", "main")
    assert xp.main(["free", "land", "fix"]) == 0
    sha = publish_merge(root)
    commit(root, manifest("1.2.0"), "later release")
    git(root, "push", "-q", "origin", "main")
    before = park_lead(root)
    git(root, "branch", "-f", "main", stale)
    git(root, "update-ref", "refs/remotes/origin/main", stale)
    assert xp.main(["free", "post-merge", "fix", "--dry-run"]) == 0
    assert wt.exists() and not git(root, "tag", "--list")
    assert xp.main(["free", "post-merge", "fix"]) == 0
    assert lead_state(root) == before
    assert trace.read_text().splitlines() == ["run"]
    assert "the merged tree is the one land recorded" in capsys.readouterr().out
    assert git(root, "rev-parse", "v1.1.1^{commit}") == sha
    record = json.loads((data / "landed.jsonl").read_text())
    assert record["merge"] == sha and "tested_by" not in record
    assert not wt.exists() and not git(root, "branch", "--list", "free-fix-x")
    assert cards.find_card("free-fix").status == "done"


@pytest.mark.parametrize("failure", ["setup", "acceptance", "none", "override"])
def test_changed_merge_recreates_resources_then_proves_patch_tree(
    tmp_path, monkeypatch, capsys, failure
):
    fake_gh(tmp_path, monkeypatch)
    trace, control = tmp_path / "trace", tmp_path / "failure"
    proof_red = tmp_path / "proof-red"
    setup = f"echo setup >> {trace}; touch bootstrap; test ! -f {control} || exit 23"
    teardown = f"echo teardown >> {trace}; rm -f bootstrap"
    config = (
        "trunk: main\nversioning: on\nversion_files: package.json\n"
        f"worktree_setup: {setup}\nworktree_teardown: {teardown}\n"
    )
    proof = (
        f"test -f bootstrap && echo acceptance >> {trace} && "
        f"pwd >> {trace} && git rev-parse HEAD >> {trace} && "
        f"test ! -f {proof_red}"
    )
    root, data, wt = free_patch(
        tmp_path,
        monkeypatch,
        proof,
        {**manifest("1.1.1"), ".xp/config.yml": config, ".gitignore": "bootstrap\n"},
    )
    # Configuration is intentionally from the invoking checkout.
    commit(root, {".xp/config.yml": config, ".gitignore": "bootstrap\n"}, "commands")
    git(root, "push", "-q", "origin", "main")
    (wt / "bootstrap").touch()
    assert xp.main(["free", "land", "fix"]) == 0
    assert not (wt / "bootstrap").exists()
    trace.write_text("")
    commit(root, {"peer": "before merge\n"}, "trunk moved before PR")
    sha = publish_merge(root)
    commit(root, {"later": "after merge\n"}, "later")
    git(root, "push", "-q", "origin", "main")
    before = park_lead(root)
    if failure in ("setup", "override"):
        control.touch()
    if failure in ("acceptance", "override"):
        proof_red.touch()
    args = ["free", "post-merge", "fix"]
    if failure == "override":
        args += ["--tested-by", "r"]
        assert xp.main([*args, "--dry-run"]) == 0
        assert trace.read_text() == "" and wt.exists()
        assert not git(root, "tag", "--list") and not (data / "landed.jsonl").exists()
    if failure in ("setup", "acceptance"):
        with pytest.raises(SystemExit) as exc:
            xp.main(args)
        err = capsys.readouterr().err
        assert exc.value.code == 2
        assert ("worktree_setup" if failure == "setup" else "Acceptance exited 1") in err
        assert not git(root, "tag", "--list") and not (data / "landed.jsonl").exists()
        assert wt.exists() and git(wt, "branch", "--show-current") == "free-fix-x"
        assert cards.find_card("free-fix").status == "in-progress"
        if failure == "setup":
            assert trace.read_text().splitlines() == ["setup"]
            assert setup in err and "23" in err and "log" in err
            control.unlink()
        else:
            proof_red.unlink()
        trace.write_text("")
    assert xp.main(args) == 0
    assert lead_state(root) == before
    lines = trace.read_text().splitlines()
    if failure == "override":
        assert lines == ["teardown"]
        assert f"warning: skipped Acceptance `{proof}`: r" in capsys.readouterr().out
    else:
        assert lines == ["setup", "acceptance", str(wt), sha, "teardown"]
    assert git(root, "rev-parse", "v1.1.1^{commit}") == sha
    record = json.loads((data / "landed.jsonl").read_text())
    assert record.get("tested_by") == ("r" if failure == "override" else None)
    assert not wt.exists()


def test_free_post_merge_accepts_squash_and_names_fetched_tip(tmp_path, monkeypatch, capsys):
    root, data, wt = free_patch(tmp_path, monkeypatch)
    stale = git(root, "rev-parse", "main")
    publish_merge(root, squash=True)
    tip = commit(root, {"later": "later\n"}, "later")
    git(root, "push", "-q", "origin", "main")
    before = park_lead(root)
    git(root, "branch", "-f", "main", stale)
    git(root, "update-ref", "refs/remotes/origin/main", stale)
    assert xp.main(["free", "post-merge", "fix"]) == 0
    out = capsys.readouterr().out
    assert "squash-merged" in out and f"fetched tip origin/main at {tip[:10]}" in out
    assert git(root, "rev-parse", "v1.1.1^{commit}") == tip and not wt.exists()
    assert json.loads((data / "landed.jsonl").read_text())["merge"] == tip
    assert lead_state(root) == before


def test_free_post_merge_unmerged_names_squash_merges(tmp_path, monkeypatch, capsys):
    free_patch(tmp_path, monkeypatch)
    with pytest.raises(SystemExit):
        land.cmd_free_post_merge(ns("fix"))
    assert "if the PR was squash- or rebase-merged" in capsys.readouterr().err


def test_free_post_merge_rerun_after_its_tag_finishes_without_tagging(tmp_path, monkeypatch):
    root, _, wt = free_patch(tmp_path, monkeypatch)
    sha = publish_merge(root)
    git(root, "tag", "-a", "v1.1.1", sha, "-m", "v1.1.1")
    commit(root, manifest("1.2.0"), "later")
    git(root, "push", "-q", "origin", "main")
    park_lead(root)

    def no_second_tag(*_):
        raise AssertionError("tagged twice")

    monkeypatch.setattr(release, "tag", no_second_tag)
    assert land.cmd_free_post_merge(ns("fix")) == 0
    assert git(root, "rev-parse", "v1.1.1^{commit}") == sha
    assert cards.find_card("free-fix").status == "done" and not wt.exists()


def test_free_patch_with_versioning_off_lands_and_closes_untagged(tmp_path, monkeypatch, capsys):
    fake_gh(tmp_path, monkeypatch)
    off = "trunk: main\nversioning: off\nroles:\n  reviewer: claude/opus\n"
    root, _, wt = free_patch(tmp_path, monkeypatch, files={".xp/config.yml": off, "f.txt": "x\n"})
    assert land.cmd_free_land(ns("fix")) == 0
    publish_merge(root)
    assert land.cmd_free_post_merge(ns("fix")) == 0
    assert git(root, "tag", "--list") == "" and not wt.exists()
    assert cards.find_card("free-fix").status == "done"
    assert "versioning: off" in capsys.readouterr().out


def test_free_post_merge_ignores_a_sprint_tag_at_head(tmp_path, monkeypatch, capsys):
    root, _, _ = free_patch(tmp_path, monkeypatch)
    publish_merge(root)
    git(root, "tag", "-a", "v1.2.0", "-m", "a sprint's tag")
    with pytest.raises(SystemExit) as exit_:
        land.cmd_free_post_merge(ns("fix"))
    assert exit_.value.code == 2 and "not after the latest tag v1.2.0" in capsys.readouterr().err
    assert cards.find_card("free-fix").status == "in-progress"


def test_free_post_merge_tags_pr_merge_after_remote_branch_update(tmp_path, monkeypatch, capsys):
    fake_gh(tmp_path, monkeypatch)
    trace = tmp_path / "runs"
    root, _, _ = free_patch(tmp_path, monkeypatch, f"echo run >> {trace}")
    assert xp.main(["free", "land", "fix"]) == 0
    commit(root, {"later": "later\n"}, "trunk moved")
    git(root, "switch", "-q", "--detach", "free-fix-x")
    git(root, "merge", "-q", "--no-ff", "main", "-m", "Update branch")
    updated = git(root, "rev-parse", "HEAD")
    git(root, "switch", "-q", "main")
    git(root, "merge", "-q", "--no-ff", updated, "-m", "PR")
    sha = git(root, "rev-parse", "HEAD")
    git(root, "push", "-q", "origin", "main")
    assert xp.main(["free", "post-merge", "fix"]) == 0
    assert trace.read_text().splitlines() == ["run", "run"]
    assert git(root, "rev-parse", "v1.1.1^{commit}") == sha
