"""A reviewed card may grow its Files and Verify obligations."""

import pytest
from close_helpers import close, launches, make_repo, ready_marker, record_round
from test_spawn_resume import finished_story, resume


def edit(tmp_path, old, new):
    plan = tmp_path / "data/plan.md"
    text = plan.read_text()
    assert old in text
    plan.write_text(text.replace(old, new))


def test_files_growth_lands_and_reports_the_added_path(tmp_path):
    repo, env, g = make_repo(tmp_path)
    sentinel = tmp_path / "story-tier-ran"
    assert g("checkout", "main").returncode == 0
    config = repo / ".xp/config.yml"
    config.write_text(config.read_text().replace("  story: true", f"  story: touch {sentinel}"))
    assert g("add", ".xp/config.yml").returncode == 0
    assert g("commit", "-qm", "set story tier").returncode == 0
    assert g("checkout", "story-042-branch").returncode == 0
    assert g("rebase", "main").returncode == 0
    credential = ready_marker(tmp_path).read_bytes()
    edit(tmp_path, "Files: src/thing.py\n", "Files: src/thing.py,\nsrc/other.py\n")
    reviewed = close(repo, env, "review")
    assert reviewed.returncode == 0, reviewed.stderr
    landed = close(repo, env, "land")
    assert landed.returncode == 0, landed.stderr
    assert sentinel.exists()
    assert landed.stdout.count("src/other.py") == 1
    assert ready_marker(tmp_path).read_bytes() == credential


def test_verify_extension_lands_and_runs_appended_command(tmp_path):
    repo, env, _g = make_repo(tmp_path)
    credential = ready_marker(tmp_path).read_bytes()
    sentinel = tmp_path / "extended-ran"
    edit(tmp_path, "Verify: true", f"Verify: true && touch {sentinel}")
    reviewed = close(repo, env, "review")
    assert reviewed.returncode == 0, reviewed.stderr
    sentinel.unlink()
    landed = close(repo, env, "land")
    assert landed.returncode == 0, landed.stderr
    assert sentinel.exists()
    assert "Verify" in landed.stdout
    assert ready_marker(tmp_path).read_bytes() == credential


def test_both_fields_can_grow_together(tmp_path):
    repo, env, _g = make_repo(tmp_path)
    edit(tmp_path, "Files: src/thing.py", "Files: src/thing.py, src/other.py")
    edit(tmp_path, "Verify: true", "Verify: true && true")
    reviewed = close(repo, env, "review")
    assert reviewed.returncode == 0, reviewed.stderr
    assert reviewed.stdout.count("card grew") == 1
    assert "src/other.py" in reviewed.stdout and "Verify: true" in reviewed.stdout


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("demo.", "changed."),
        ("Then Z", "Then different"),
        ("demo story", "renamed story"),
        ("Files: src/thing.py", "Files: src/other.py"),
        ("Files: src/thing.py", "Files: src/thing.py, .xp/local.md"),
        ("Files: src/thing.py", "Files: src/thing.py, .xp/system.md"),
        ("Verify: true", "Verify: false"),
        ("Verify: true", "Verify: true&&true"),
    ],
)
def test_other_edits_refuse_before_review_launch(tmp_path, old, new):
    repo, env, _g = make_repo(tmp_path)
    credential = ready_marker(tmp_path).read_bytes()
    edit(tmp_path, old, new)
    review = close(repo, env, "review")
    assert review.returncode == 2 and "was edited after its plan review" in review.stderr
    assert "spawn.py amend story-042" in review.stderr
    assert launches(tmp_path) == []
    record_round(repo, env, tmp_path)
    land = close(repo, env, "land", "--dry-run")
    assert land.returncode == 2 and land.stderr == review.stderr
    assert ready_marker(tmp_path).read_bytes() == credential


def test_files_growth_allows_resume(tmp_path):
    repo, env, _g, _tree, _marker = finished_story(tmp_path)
    edit(tmp_path, "Files: src/thing.py", "Files: src/thing.py, src/other.py")
    result = resume(repo, env, "--dry-run")
    assert result.returncode == 0, result.stderr
    assert "src/other.py" in result.stdout


def test_removing_a_verify_command_refuses_before_review(tmp_path):
    repo, env, _g = make_repo(tmp_path, verify="true && true")
    edit(tmp_path, "Verify: true && true", "Verify: true")
    result = close(repo, env, "review")
    assert result.returncode == 2 and "was edited after its plan review" in result.stderr
    assert launches(tmp_path) == []


def test_moving_files_field_is_not_growth(tmp_path):
    repo, env, _g = make_repo(tmp_path)
    edit(
        tmp_path,
        "Context: demo.\nFiles: src/thing.py",
        "Files: src/thing.py, src/other.py\nContext: demo.",
    )
    result = close(repo, env, "review")
    assert result.returncode == 2 and "was edited after its plan review" in result.stderr
    assert launches(tmp_path) == []
