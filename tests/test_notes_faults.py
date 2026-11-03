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


@pytest.mark.parametrize("kind", ["free", "sprint"])
def test_land_uses_fetched_target_mode(tmp_path, monkeypatch, capsys, kind):
    gh = fake_gh(tmp_path, monkeypatch)
    root, data, tree, branch, identifier, trace = branch_project(
        tmp_path, monkeypatch, kind, mode="off"
    )
    if kind == "sprint":
        git(root, "add", ".githooks/sprint")
        git(root, "commit", "-qm", "sprint hook")
    stale = git(root, "rev-parse", "main")
    if kind == "sprint":
        git(root, "switch", "-q", "main")
    commit(root, {".xp/config.yml": CONFIG}, "enable notes on trunk")
    git(root, "push", "-q", "origin", "main")
    if kind == "sprint":
        git(root, "switch", "-q", branch)
        git(root, "branch", "-f", "main", stale)
    else:
        git(root, "reset", "--hard", stale)
    git(root, "update-ref", "refs/remotes/origin/main", stale)
    monkeypatch.chdir(tree)
    note = f"changes/{branch}.md"
    commit(tree, {note: "A change.\nRelease steps: none.\n"}, "invalid note")
    args = [kind, "land", identifier]
    with pytest.raises(SystemExit) as exc:
        xp.main(args)
    err = capsys.readouterr().err
    assert exc.value.code == 2 and note in err and "Bump:" in err
    assert not trace.exists() and not gh.exists()
    assert not git(root, "ls-remote", "--heads", "origin", branch)
    if kind == "free":
        assert cards.find_card("free-fix").status == "in-progress"
        record = data / "stories/free-fix/tested_tree"
    else:
        record = data / "sprints/1/land.json"
    assert not record.exists()
    commit(tree, {note: NOTE}, "correct note")
    assert xp.main(args) == 0
    assert trace.read_text() == "ran\n" and gh.exists() and record.is_file()
    assert git(root, "ls-remote", "--heads", "origin", branch)
