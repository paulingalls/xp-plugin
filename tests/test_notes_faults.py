import pytest
import xp
from test_land import commit, fake_gh, git
from test_notes import CONFIG, NOTE, branch_project, pending, project, race_hook
from xpcore import cards


def test_local_changes_during_rejected_push_survive(tmp_path, monkeypatch, capsys):
    root, _ = project(tmp_path, monkeypatch)
    pending(root)
    race_hook(tmp_path, root, "stamp", "echo preserve > untracked\necho preserve >> CHANGELOG.md")
    with pytest.raises(SystemExit) as exc:
        xp.main(["release", "stamp"])
    assert exc.value.code == 2
    assert "local state changed during push; inspect" in capsys.readouterr().err
    assert (root / "untracked").read_text() == "preserve\n"
    assert (root / "CHANGELOG.md").read_text().endswith("preserve\n")
    assert git(root, "rev-parse", "HEAD") != git(root, "rev-parse", "origin/main")


@pytest.mark.parametrize("kind", ["free", "sprint"])
def test_post_merge_refuses_malformed_pending_note(tmp_path, monkeypatch, capsys, kind):
    fake_gh(tmp_path, monkeypatch)
    root, data, tree, branch, identifier, _ = branch_project(tmp_path, monkeypatch, kind)
    commit(tree, {f"changes/{branch}.md": NOTE}, "valid note")
    assert xp.main([kind, "land", identifier]) == 0
    if kind == "sprint":
        git(root, "switch", "-q", "main")
    commit(
        root,
        {
            "changes/peer.md": "Peer change.\nRelease steps: none.\n",
            "changes/README.md": "Instructions only.\n",
        },
        "peer note",
    )
    git(root, "merge", "-q", "--no-ff", branch, "-m", "PR")
    git(root, "push", "-q", "origin", "main")
    commit(root, {".xp/config.yml": CONFIG.replace("notes", "off")}, "stale local mode")
    with pytest.raises(SystemExit) as exc:
        xp.main([kind, "post-merge", identifier, "--tested-by", "external proof"])
    err = capsys.readouterr().err
    assert exc.value.code == 2 and "changes/peer.md" in err and "Bump:" in err
    assert git(root, "tag", "--list") == "v1.1.0"
    assert git(root, "branch", "--list", branch)
    if kind == "free":
        assert tree.exists() and cards.find_card("free-fix").status == "in-progress"
        assert not (data / "landed.jsonl").exists()
    else:
        assert (data / "sprint_branch").read_text() == branch
        assert not (data / "sprints/1/release.json").exists()
