import pytest
from test_land import CHECK, commit, fake_gh, free_patch, git, manifest, ns
from xpcore import cards, land, release


def test_free_post_merge_runs_acceptance_on_trunk_before_tagging(tmp_path, monkeypatch, capsys):
    fake_gh(tmp_path, monkeypatch)
    files = {**manifest("1.1.1"), "check.py": CHECK, "merged.txt": "ok\n"}
    root, _, wt = free_patch(tmp_path, monkeypatch, "python3 check.py", files)
    assert land.cmd_free_land(ns("fix")) == 0
    git(root, "merge", "-q", "--no-ff", "free-fix-x", "-m", "PR")
    commit(root, {"merged.txt": "bad\n"}, "trunk broke it")
    with pytest.raises(SystemExit) as exit_:
        land.cmd_free_post_merge(ns("fix"))
    err = capsys.readouterr().err
    assert exit_.value.code == 2 and "Acceptance exited 1 on main at " in err
    assert "then run xp.py free post-merge fix again" in err
    assert git(root, "tag", "--list", "v1.1.1") == ""
    assert cards.find_card("free-fix").status == "in-progress" and wt.exists()


def test_free_post_merge_skips_acceptance_on_the_tree_land_tested(tmp_path, monkeypatch, capsys):
    fake_gh(tmp_path, monkeypatch)
    trace = tmp_path / "runs"
    root, _, _ = free_patch(tmp_path, monkeypatch, f"echo run >> {trace}")
    assert land.cmd_free_land(ns("fix")) == 0
    git(root, "merge", "-q", "--no-ff", "free-fix-x", "-m", "PR")
    assert land.cmd_free_post_merge(ns("fix")) == 0
    assert trace.read_text().splitlines() == ["run"]
    assert "the merged tree is the one land recorded" in capsys.readouterr().out
    assert git(root, "cat-file", "-t", "v1.1.1") == "tag"


def test_free_post_merge_accepts_a_squash_merge_and_discourages_it(tmp_path, monkeypatch, capsys):
    root, _, wt = free_patch(tmp_path, monkeypatch)
    git(root, "merge", "-q", "--squash", "free-fix-x")
    git(root, "commit", "-qm", "squashed PR")
    assert land.cmd_free_post_merge(ns("fix")) == 0
    assert "free-fix was squash-merged; its history is not on main" in capsys.readouterr().out
    assert git(root, "cat-file", "-t", "v1.1.1") == "tag" and not wt.exists()


def test_free_post_merge_unmerged_names_squash_merges(tmp_path, monkeypatch, capsys):
    free_patch(tmp_path, monkeypatch)
    with pytest.raises(SystemExit):
        land.cmd_free_post_merge(ns("fix"))
    assert "if the PR was squash- or rebase-merged" in capsys.readouterr().err


def test_free_post_merge_rerun_after_its_tag_finishes_without_tagging(tmp_path, monkeypatch):
    root, _, wt = free_patch(tmp_path, monkeypatch)
    git(root, "merge", "-q", "--no-ff", "free-fix-x", "-m", "PR")
    git(root, "tag", "-a", "v1.1.1", "-m", "v1.1.1")

    def no_second_tag(_):
        raise AssertionError("tagged twice")

    monkeypatch.setattr(release, "tag", no_second_tag)
    assert land.cmd_free_post_merge(ns("fix")) == 0
    assert cards.find_card("free-fix").status == "done" and not wt.exists()


def test_free_patch_with_versioning_off_lands_and_closes_untagged(tmp_path, monkeypatch, capsys):
    fake_gh(tmp_path, monkeypatch)
    off = "trunk: main\nversioning: off\nroles:\n  reviewer: claude/opus\n"
    root, _, wt = free_patch(tmp_path, monkeypatch, files={".xp/config.yml": off, "f.txt": "x\n"})
    assert land.cmd_free_land(ns("fix")) == 0
    git(root, "merge", "-q", "--no-ff", "free-fix-x", "-m", "PR")
    assert land.cmd_free_post_merge(ns("fix")) == 0
    assert git(root, "tag", "--list") == "" and not wt.exists()
    assert cards.find_card("free-fix").status == "done"
    assert "versioning: off" in capsys.readouterr().out


def test_free_post_merge_ignores_a_sprint_tag_at_head(tmp_path, monkeypatch, capsys):
    root, _, _ = free_patch(tmp_path, monkeypatch)
    git(root, "merge", "-q", "--no-ff", "free-fix-x", "-m", "PR")
    git(root, "tag", "-a", "v1.2.0", "-m", "a sprint's tag")
    with pytest.raises(SystemExit) as exit_:
        land.cmd_free_post_merge(ns("fix"))
    assert exit_.value.code == 2 and "not after the latest tag v1.2.0" in capsys.readouterr().err
    assert cards.find_card("free-fix").status == "in-progress"
