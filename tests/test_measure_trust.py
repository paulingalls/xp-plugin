import xp
from test_land import commit, make_project


def test_recover_shows_measures_but_never_runs_repo_shell(tmp_path, monkeypatch, capsys):
    root, _ = make_project(tmp_path, monkeypatch)
    commit(root, {".xp/milestones.md": "## Goal\nMeasure: touch pwned; echo ran\n"}, "goals")
    assert xp.main(["recover"]) == 0
    out = capsys.readouterr().out
    assert not (root / "pwned").exists()
    assert "Goal — not run: touch pwned; echo ran" in out
