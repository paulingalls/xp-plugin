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


def test_frontmatter_is_dropped_and_every_path_is_listed(repo, tmp_path, monkeypatch):
    (tmp_path / "agents").mkdir()
    (tmp_path / "agents" / "x.md").write_text("---\nname: x\n---\nWrite the plan.\n")
    monkeypatch.setattr(config, "plugin_root", lambda: tmp_path)
    text = bundle.prompt("x", card="slate", paths={"PLAN_PATH": "/p.md", "CARD_ID": "s-1"})
    assert "Write the plan." in text and "- PLAN_PATH: /p.md" in text and "- CARD_ID: s-1" in text
    assert "name: x" not in text and "===== Card =====\nslate" in text


def test_a_slate_is_its_own_section_not_a_card(repo):
    text = bundle.prompt("angle-reviewer", slate="## Sprint 1", angle="Q?")
    assert "===== Slate =====\n## Sprint 1" in text and "===== Card" not in text
    assert "===== Angle =====\nQ?" in text


def test_every_charter_is_three_short_sections(repo):
    for path in sorted((config.plugin_root() / "agents").glob("*.md")):
        lines = path.read_text().splitlines()
        assert len(lines) <= 40, path.name
        assert [ln for ln in lines if ln.startswith("## ")] == ["## Read", "## Produce", "## Own"]


def test_missing_charter_refuses(repo, capsys):
    with pytest.raises(SystemExit):
        bundle.prompt("nobody", card="c")
    assert "no charter" in capsys.readouterr().err
