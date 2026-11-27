import re
import time

import pytest
import xp
from test_land import commit, git, make_project
from test_land import story as story
from xpcore import session

MILESTONES = """# Milestones
<!--
## Example
Measure: echo hidden
-->
## First
Measure: cat first.txt
## Second
Measure: cat second.txt
## Unmeasured
Goal: still visible
"""
FILES = {
    ".xp/milestones.md": MILESTONES,
    "first.txt": "distance=2\n",
    "second.txt": "distance=3\n",
}


def label(root, dirty=False):
    branch = git(root, "branch", "--show-current")
    sha = git(root, "rev-parse", "HEAD")[:7]
    return rf"\(\d+\.\d+s; {branch} @{sha}{', dirty' if dirty else ''}\)$"


def snapshot(root):
    return git(root, "rev-parse", "HEAD"), git(root, "status", "--porcelain")


def readings(capsys, slug):
    """Free mint is a deliberate command, so it runs the Measures; recover only shows them."""
    assert xp.main(["free", slug]) == 0
    out = capsys.readouterr().out.splitlines()
    if session.BEGIN not in out:
        return []
    return out[out.index(session.BEGIN) + 1 : out.index(session.END)]


@pytest.mark.parametrize("dirty", [False, True])
def test_mint_measures_invoking_tree_without_writing(tmp_path, monkeypatch, capsys, dirty):
    root, data = make_project(tmp_path, monkeypatch)
    (data / "plan.md").write_text("# Plan\n")
    commit(root, FILES, "goals")
    (root / "nested").mkdir()
    if dirty:
        (root / "untracked").touch()
    before = snapshot(root)
    monkeypatch.chdir(root / "nested")
    lines = readings(capsys, "first")
    for line, title, result in zip(
        lines[:2], ("First", "Second"), ("distance=2", "distance=3"), strict=True
    ):
        assert line.startswith(f"{title} — {result} ")
        assert re.search(label(root, dirty), line)
    assert lines[2:] == ["Unmeasured — no Measure"]
    assert "hidden" not in "\n".join(lines)
    assert snapshot(root) == before
    (root / ".xp/milestones.md").unlink()
    assert readings(capsys, "second") == []


@pytest.mark.parametrize(
    "command, status",
    [
        ("exit 1", "exit 1"),
        ("no-such-milestone-command-xp", "exit 127"),
        ("sleep 10", "timed out"),
    ],
)
def test_failed_measure_reports_output_and_continues(
    tmp_path, monkeypatch, capsys, command, status
):
    root, data = make_project(tmp_path, monkeypatch)
    commit(
        root,
        {
            ".xp/milestones.md": (
                f"## Failing\nMeasure: echo partial; echo diagnostic >&2; {command}\n"
                "## Following\nMeasure: echo remaining\n"
            )
        },
        "goals",
    )
    (data / "plan.md").write_text("# Plan\n")
    if status == "timed out":
        monkeypatch.setattr(session, "MEASURE_TIMEOUT", 0.1, raising=False)
    started = time.monotonic()
    lines = readings(capsys, "patch")
    assert time.monotonic() - started < 5
    assert all(text in lines[0] for text in ("Failing —", "partial", "diagnostic", status))
    assert lines[1].startswith("Following — remaining ")
    assert all(re.search(label(root), line) for line in lines)


def test_recover_outside_repo_and_before_first_commit(tmp_path, monkeypatch, capsys):
    data = tmp_path / "data"
    data.mkdir()
    (data / "session.md").write_text("digest\n")
    monkeypatch.setenv("XP_DATA", str(data))
    monkeypatch.chdir(tmp_path)
    assert xp.main(["recover"]) == 0
    assert capsys.readouterr().out.startswith("digest\n")
    root = tmp_path / "new"
    git(tmp_path, "init", "-q", "-b", "main", str(root))
    (root / ".xp").mkdir()
    (root / ".xp/milestones.md").write_text("## New\nMeasure: echo distance\n")
    monkeypatch.chdir(root)
    assert xp.main(["recover"]) == 0
    out = capsys.readouterr().out
    assert out.startswith(f"{session.BEGIN}\nNew — not run: echo distance\n{session.END}\ndigest\n")


def test_story_land_without_running_measures(story, capsys):
    from xpcore import cards

    root, _, wt, _ = story
    commit(
        root,
        {
            ".xp/milestones.md": "## First\nMeasure: touch measure-ran\n",
            "merged.txt": "ok\n",
        },
        "sprint goals",
    )
    assert xp.main(["story", "land", "story-001"]) == 0
    out = capsys.readouterr().out
    assert "story-001 landed on sprint-001" in out
    assert cards.find_card("story-001").status == "done" and not wt.exists()
    assert not (root / "measure-ran").exists()
    assert session.BEGIN not in out


def test_free_mint_measures_before_next_instruction(tmp_path, monkeypatch, capsys):
    root, data = make_project(tmp_path, monkeypatch)
    (data / "plan.md").write_text("# Plan\n")
    commit(root, FILES, "goals")
    assert xp.main(["free", "new-patch"]) == 0
    out = capsys.readouterr().out
    assert out.index("minted under ## Free") < out.index("First — distance=2")
    assert out.index("Second — distance=3") < out.index("next: write Context")
    for line in out.splitlines():
        if line.startswith(("First —", "Second —")):
            assert re.search(label(root), line)


def test_free_mint_without_milestones_says_to_copy_the_template(tmp_path, monkeypatch, capsys):
    _, data = make_project(tmp_path, monkeypatch)
    (data / "plan.md").write_text("# Plan\n")
    assert xp.main(["free", "first-patch"]) == 0
    out = capsys.readouterr().out
    template = session.plugin_root() / "templates" / "milestones.md"
    assert f"no .xp/milestones.md: copy {template} there" in out
    assert out.index("no .xp/milestones.md") < out.index("next: write Context")
