import pytest
import xp
from test_land import git
from test_notes import pending, project, race_hook


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
