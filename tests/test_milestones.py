import re
import time

import pytest
import xp
from test_land import commit, git, make_project
from test_land import story as story
from test_sprint import repo as repo
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
    branch = git(root, "branch", "--show-current") or "detached HEAD"
    sha = git(root, "rev-parse", "HEAD")[:7]
    return rf"\(\d+\.\d+s; {branch} @{sha}{', dirty' if dirty else ''}\)$"


def snapshot(root, data):
    return (
        git(root, "rev-parse", "HEAD"),
        git(root, "status", "--porcelain"),
        {str(p.relative_to(data)): p.read_bytes() for p in data.rglob("*") if p.is_file()},
    )


@pytest.mark.parametrize("dirty", [False, True])
def test_recover_measures_invoking_tree_first_without_writing(tmp_path, monkeypatch, capsys, dirty):
    root, data = make_project(tmp_path, monkeypatch)
    commit(root, FILES, "goals")
    (data / "session.md").write_text("distinct digest\n")
    (root / "nested").mkdir()
    if dirty:
        (root / "untracked").touch()
    before = snapshot(root, data)
    monkeypatch.chdir(root / "nested")
    assert xp.main(["recover"]) == 0
    lines = capsys.readouterr().out.splitlines()
    for line, title, result in zip(
        lines[:2], ("First", "Second"), ("distance=2", "distance=3"), strict=True
    ):
        assert line.startswith(f"{title} — {result} ")
        assert re.search(label(root, dirty), line)
    assert lines[2:4] == ["Unmeasured — no Measure", "distinct digest"]
    assert "hidden" not in "\n".join(lines)
    assert snapshot(root, data) == before
    (root / ".xp/milestones.md").unlink()
    assert xp.main(["recover"]) == 0
    assert capsys.readouterr().out.startswith("distinct digest\n\n## cards")


@pytest.mark.parametrize(
    "command, status",
    [
        ("exit 1", "exit 1"),
        ("no-such-milestone-command-xp", "exit 127"),
        ("sleep 2", "timed out"),
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
    (data / "session.md").write_text("digest\n")
    if status == "timed out":
        monkeypatch.setattr(session, "MEASURE_TIMEOUT", 0.1, raising=False)
    started = time.monotonic()
    assert xp.main(["recover"]) == 0
    assert time.monotonic() - started < 5
    lines = capsys.readouterr().out.splitlines()
    assert all(text in lines[0] for text in ("Failing —", "partial", "diagnostic", status))
    assert lines[1].startswith("Following — remaining ")
    assert all(re.search(label(root), line) for line in lines[:2])
    assert lines[2] == "digest"


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
    assert re.match(r"New — distance \(\d+\.\d+s; main @no commits, dirty\)\ndigest\n", out)


def test_story_land_measures_new_merge_in_invoking_checkout(story, capsys):
    from xpcore import cards

    root, _, wt, _ = story
    commit(root, FILES | {"merged.txt": "ok\n"}, "sprint goals")
    assert xp.main(["story", "land", "story-001"]) == 0
    out = capsys.readouterr().out
    assert out.index("story-001 landed on sprint-001") < out.index("First — distance=2")
    for line in out.splitlines():
        if line.startswith(("First —", "Second —")):
            assert re.search(label(root), line)
    assert cards.find_card("story-001").status == "done" and not wt.exists()


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


def test_free_post_merge_measures_only_on_recover(tmp_path, monkeypatch, capsys):
    from test_free_post_merge import publish_merge
    from test_land import fake_gh, free_patch

    fake_gh(tmp_path, monkeypatch)
    root, _, wt = free_patch(tmp_path, monkeypatch)
    commit(wt, FILES, "goals")
    assert xp.main(["free", "land", "fix"]) == 0
    publish_merge(root)
    capsys.readouterr()
    assert xp.main(["free", "post-merge", "fix"]) == 0
    assert "distance=" not in capsys.readouterr().out
    assert git(root, "rev-parse", "v1.1.1^{commit}") == git(root, "rev-parse", "HEAD")
    assert xp.main(["recover"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[0].startswith("First — distance=2") and re.search(label(root), lines[0])


def test_sprint_post_merge_measures_only_on_recover(repo, tmp_path, monkeypatch, capsys):
    from test_land import fake_gh
    from test_sprint import merge_on_trunk

    root, _, _ = repo
    fake_gh(tmp_path, monkeypatch)
    commit(root, FILES, "goals")
    assert xp.main(["sprint", "land", "1"]) == 0
    merge_on_trunk(root)
    capsys.readouterr()
    assert xp.main(["sprint", "post-merge", "1"]) == 0
    assert "distance=" not in capsys.readouterr().out
    assert git(root, "rev-parse", "v1.2.0^{commit}") == git(root, "rev-parse", "HEAD")
    assert xp.main(["recover"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[0].startswith("First — distance=2") and re.search(label(root), lines[0])
