import xp
from test_land import git
from test_retro_wiki import sighting

pytest_plugins = ["test_retro_filing"]


def test_secret_never_pushed(publishing, monkeypatch, capsys):
    root = publishing[0]
    wiki = root.parent / "origin.wiki.git"
    before = git(wiki, "rev-parse", "HEAD")
    (root / ".gitleaks.toml").write_text(
        '[[rules]]\nid = "canary"\nregex = "xp_canary_[a-f0-9]{8}"\n'
    )
    sighting(monkeypatch, "xp_canary_0123abcd")
    assert xp.main(["retro", "1"]) == 1
    assert "gitleaks refused" in capsys.readouterr().err
    assert git(wiki, "rev-parse", "HEAD") == before
    for commit in git(wiki, "rev-list", "--all").splitlines():
        assert "xp_canary_0123abcd" not in git(wiki, "show", commit)
