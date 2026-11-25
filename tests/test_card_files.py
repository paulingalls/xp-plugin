import pytest
import xp
from test_story import repo as repo
from test_story import roles


def assert_files_refusal(capsys, exit_, data, card_id):
    err = capsys.readouterr().err
    assert exit_.value.code == 2
    assert card_id in err and "Files:" in err
    assert "comma-separated" in err and "one line" in err
    assert roles(data) == []


@pytest.mark.parametrize("command", [["sprint", "plan", "1"], ["story", "story-002"]])
@pytest.mark.parametrize("dry", [False, True])
@pytest.mark.parametrize(
    "files",
    ["Files:\n- a.py\n- b.py", "Files: a.py,\n  b.py", "Files:", ""],
    ids=["bulleted", "trailing-comma", "empty", "missing"],
)
def test_malformed_files_refused_before_agents(repo, capsys, command, dry, files):
    plan = repo / "plan.md"
    text = plan.read_text().replace("Files: a.py\n", files + "\nAcceptance: true\n")
    plan.write_text(text)
    review = repo / "sprints" / "1" / "slate-review.md"
    review.parent.mkdir(parents=True)
    review.write_text("previous review\n")

    with pytest.raises(SystemExit) as exit_:
        xp.main([*command, *(["--dry-run"] if dry else [])])

    assert_files_refusal(capsys, exit_, repo, "story-002")
    assert plan.read_text() == text
    assert review.read_text() == "previous review\n"
    assert not (repo / "stories" / "story-002").exists()
    assert not (repo / "worktrees").exists()


@pytest.mark.parametrize("dry", [False, True])
def test_existing_unfilled_free_card_refused(repo, capsys, dry):
    assert xp.main(["free", "fix-files"]) == 0
    plan = repo / "plan.md"
    text = plan.read_text()
    assert text.endswith("#### free-fix-files — fix-files   [planned]\n")
    assert not (repo / "worktrees").exists() and roles(repo) == []
    capsys.readouterr()

    with pytest.raises(SystemExit) as exit_:
        xp.main(["free", "fix-files", *(["--dry-run"] if dry else [])])

    assert_files_refusal(capsys, exit_, repo, "free-fix-files")
    assert plan.read_text() == text
    assert not (repo / "stories" / "free-fix-files").exists()
    assert not (repo / "worktrees").exists()


def test_fresh_free_dry_run_previews_unfilled_card(repo, capsys):
    plan = repo / "plan.md"
    text = plan.read_text()

    assert xp.main(["free", "fix-files", "--dry-run"]) == 0

    out = capsys.readouterr().out
    assert "free-fix-files: would mint" in out
    assert "would run worktree, executor, reviewer" in out
    assert plan.read_text() == text and roles(repo) == []
    assert not (repo / "stories" / "free-fix-files").exists()
    assert not (repo / "worktrees").exists()
