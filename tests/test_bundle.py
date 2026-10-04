import subprocess

import pytest
from xpcore import bundle, cards, config


@pytest.fixture
def repo(tmp_path, monkeypatch):
    subprocess.run(["git", "init", "-q", str(tmp_path / "repo")], check=True)
    (tmp_path / "repo" / ".xp").mkdir()
    monkeypatch.setenv("XP_DATA", str(tmp_path / "data"))
    monkeypatch.chdir(tmp_path / "repo")
    return tmp_path / "repo"


CARD = cards.Card("story-001", "t", "planned", ["#### story-001 — t   [planned]", "Files: a"])


def test_prompt_assembles_every_part_and_appends_paths(repo, tmp_path):
    (repo / ".xp" / "constraints.md").write_text("1. No globals.")
    text = bundle.prompt(
        "reviewer",
        card=CARD,
        plan="the plan",
        findings="F1",
        paths={"FINDINGS_PATH": "/d/review-1.md"},
    )
    for part in ("XP Values", "# Reviewer", "1. No globals.", "Files: a", "the plan", "F1"):
        assert part in text
    assert "description:" not in text and "Project system" not in text
    assert text.index("# Reviewer") < text.index("Files: a") < text.index("===== Paths")
    assert f"- DATA: {tmp_path / 'data'}" in text and "- FINDINGS_PATH: /d/review-1.md" in text


def test_placeholders_are_substituted_not_appended(repo, tmp_path, monkeypatch):
    (tmp_path / "agents").mkdir()
    (tmp_path / "agents" / "x.md").write_text("---\nname: x\n---\nWrite {PLAN_PATH}.\n")
    monkeypatch.setattr(config, "plugin_root", lambda: tmp_path)
    text = bundle.prompt("x", card="slate", paths={"PLAN_PATH": "/p.md", "CARD_ID": "s-1"})
    assert "Write /p.md." in text and "PLAN_PATH" not in text and "- CARD_ID: s-1" in text
    assert "name: x" not in text and "===== Card =====\nslate" in text


def test_missing_charter_refuses(repo, capsys):
    with pytest.raises(SystemExit):
        bundle.prompt("nobody", card="c")
    assert "no charter" in capsys.readouterr().err
