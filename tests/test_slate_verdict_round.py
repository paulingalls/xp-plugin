"""A reviewer's complete verdict spends its round even when the reviewer dies."""

import json
import subprocess
import sys
from pathlib import Path

import pytest
from slate_review_helpers import SLATE_REVIEW, slate_repo, slate_review, stub_slate_reviewer


def dead_reviewer(tmp_path, findings="## story-042 — GREEN\n\n## Slate — GREEN\n", slate=""):
    launch = stub_slate_reviewer(tmp_path, findings=findings, slate=slate)
    binary = tmp_path / "bin" / "claude"
    binary.write_text(
        binary.read_text().replace("print(json.dumps(", "sys.exit(9)\nprint(json.dumps(")
    )
    return launch


def artifacts(env):
    root = Path(env["XP_DATA"])
    return root / "slate-reviews", root / "markers" / "1.slate-review-incomplete"


def test_dead_reviewer_with_complete_verdict_spends_round_and_reports_error(tmp_path):
    repo, env = slate_repo(tmp_path)
    dead_reviewer(tmp_path)

    result = slate_review(repo, env)

    rounds, marker = artifacts(env)
    assert result.returncode == 2
    assert "exit" in result.stderr.lower() and "9" in result.stderr
    assert "sprint-1.round-1.md spent this round" in result.stderr
    assert (rounds / "sprint-1.round-1.md").read_text().startswith("## story-042 — GREEN")
    assert not list(rounds.glob("*.failed-*.md"))
    assert not marker.exists()


def test_two_dead_reviewers_with_verdicts_reach_cap_without_third_launch(tmp_path):
    repo, env = slate_repo(tmp_path)
    launch = dead_reviewer(tmp_path)
    for number in (1, 2):
        result = slate_review(repo, env)
        assert result.returncode == 2, result.stderr
        assert (Path(env["XP_DATA"]) / "slate-reviews" / f"sprint-1.round-{number}.md").exists()
    launch.unlink()

    result = slate_review(repo, env)

    rounds, marker = artifacts(env)
    assert result.returncode == 2 and "two slate-review rounds" in result.stderr
    assert not launch.exists() and not (rounds / "sprint-1.round-3.md").exists()
    assert not list(rounds.glob("*.failed-*.md")) and not marker.exists()


def test_child_verdict_counts_before_waiter_clears_marker(tmp_path, monkeypatch):
    repo, env = slate_repo(tmp_path)
    dead_reviewer(tmp_path)
    rounds, marker = artifacts(env)
    rounds.mkdir()
    marker.parent.mkdir(exist_ok=True)
    first = rounds / "sprint-1.round-1.md"
    marker.write_text(json.dumps({"findings": str(first)}))

    child = subprocess.run(
        [sys.executable, str(SLATE_REVIEW), "1", "--_review", str(first)],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
    )

    assert child.returncode == 2
    assert first.exists() and marker.exists()
    monkeypatch.setenv("XP_DATA", env["XP_DATA"])
    from review_runner import completed_review_rounds, review_findings_path

    assert [n for n, _ in completed_review_rounds("1", "slate")] == [1]
    assert review_findings_path("1", "slate").name == "sprint-1.round-2.md"
    from sprint_close import supersede_slate_marker

    assert supersede_slate_marker("1") == ""
    assert first.exists() and not list(rounds.glob("*.failed-*.md"))
    result = slate_review(repo, env)
    assert result.returncode == 2 and (rounds / "sprint-1.round-2.md").exists()
    assert first.exists()


@pytest.mark.parametrize(
    "findings,extra_card",
    [
        ("## story-042 — GREEN\n", ""),
        ("## story-042 — GREEN\n\n## Slate — GREEN\n", "#### story-043 — second   [planned]\n"),
        ("## story-042 — GREEN\n\nProse says ## Slate — GREEN\n", ""),
        ("## story-042 — GREEN\n\n### Slate — GREEN\n", ""),
        ("  ## story-042 — GREEN\n\n## Slate — GREEN\n", ""),
    ],
)
def test_incomplete_verdict_is_archived_and_retryable(tmp_path, findings, extra_card):
    repo, env = slate_repo(tmp_path)
    if extra_card:
        plan = Path(env["XP_DATA"]) / "plan.md"
        plan.write_text(plan.read_text() + extra_card)
    dead_reviewer(tmp_path, findings)

    result = slate_review(repo, env)

    rounds, marker = artifacts(env)
    assert result.returncode == 2
    assert not (rounds / "sprint-1.round-1.md").exists()
    assert len(list(rounds.glob("sprint-1.round-1.failed-*.md"))) == 1
    assert marker.exists()


@pytest.mark.parametrize("change", ["repo", "slate"])
def test_mutation_refusal_wins_over_complete_verdict(tmp_path, change):
    repo, env = slate_repo(tmp_path)
    slate = str(Path(env["XP_DATA"]) / "plan.md") if change == "slate" else ""
    dead_reviewer(tmp_path, slate=slate)
    if change == "repo":
        binary = tmp_path / "bin" / "claude"
        binary.write_text(
            binary.read_text().replace(
                "path = re.search(",
                "open('drift.txt', 'a').write('changed\\n')\npath = re.search(",
            )
        )

    result = slate_review(repo, env)

    rounds, marker = artifacts(env)
    assert result.returncode == 2 and "changed the repository or the slate" in result.stderr
    assert not (rounds / "sprint-1.round-1.md").exists()
    assert len(list(rounds.glob("sprint-1.round-1.failed-*.md"))) == 1
    assert marker.exists()
