import os
import subprocess
import sys

import pytest
import xp

FAKE = """\
import json, os, re, subprocess, sys
prompt = sys.stdin.read()
paths = dict(re.findall(r"^- ([A-Z_]+): (.+)$", prompt, re.M))
role = os.environ["XP_ROLE"]
key = {"planner": "PLAN_PATH", "executor": "HANDBACK_PATH"}.get(role, "FINDINGS_PATH")
extra = os.environ.get("FAKE_QUESTION", "") if role == "plan-reviewer" else ""
with open(paths[key], "w") as out:
    out.write(f"{role} wrote this\\n{extra}\\n")
if role == "executor":
    with open("feature.txt", "a") as out:
        out.write("x\\n")
    subprocess.run(["git", "add", "-A"], check=True)
    subprocess.run(["git", "commit", "-qm", "feat"], check=True)
print(json.dumps({"type": "result", "result": "done"}))
"""
PLAN = """\
## Sprint 1 — s
#### story-001 — Add the widget   [planned]
Context: c.
Files: a.py, b.py
Acceptance: true
#### story-002 — One file   [planned]
Files: a.py
"""


def git(*args, cwd):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


@pytest.fixture
def repo(tmp_path, monkeypatch):
    root, data, bin_dir = tmp_path / "repo", tmp_path / "data", tmp_path / "bin"
    for path in (root / ".xp", data, bin_dir):
        path.mkdir(parents=True)
    (root / ".xp" / "config.yml").write_text(
        "roles:\n  planner: claude/s\n  executor: claude/s\n  reviewer: claude/o\n"
    )
    for var in ("GIT_AUTHOR", "GIT_COMMITTER"):
        monkeypatch.setenv(f"{var}_NAME", "t")
        monkeypatch.setenv(f"{var}_EMAIL", "t@e")
    git("init", "-q", "-b", "main", cwd=root)
    git("add", "-A", cwd=root)
    git("commit", "-qm", "init", cwd=root)
    git("checkout", "-qb", "sprint-001", cwd=root)
    git("commit", "-q", "--allow-empty", "-m", "sprint work", cwd=root)
    git("checkout", "-q", "main", cwd=root)
    (data / "sprint_branch").write_text("sprint-001\n")
    (data / "plan.md").write_text(PLAN)
    (bin_dir / "claude").write_text(f"#!{sys.executable}\n{FAKE}")
    (bin_dir / "claude").chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("XP_DATA", str(data))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.chdir(root)
    return data


def story(data, card_id):
    return data / "stories" / card_id


def test_single_file_card_skips_planning(repo):
    assert xp.main(["story", "story-002"]) == 0
    assert sorted(p.name for p in story(repo, "story-002").iterdir()) == [
        "handback.md",
        "review-1.md",
    ]
    assert not (repo / "logs" / "story-002-planner.log").exists()


def test_full_walk_then_rerun_is_a_noop(repo, capsys):
    assert xp.main(["story", "story-001"]) == 0
    sdir = story(repo, "story-001")
    names = {"plan.md", "plan-review.md", "handback.md", "review-1.md"}
    assert {p.name for p in sdir.iterdir()} == names
    assert "[in-progress]" in (repo / "plan.md").read_text().splitlines()[1]
    wt = repo / "worktrees" / "story-001"
    assert git("branch", "--show-current", cwd=wt).stdout.strip() == "story-001-add-the-widget"
    assert git("log", "--format=%s", "sprint-001..HEAD", cwd=wt).stdout.split() == ["feat"]
    out = capsys.readouterr().out
    assert f"review at {sdir / 'review-1.md'}" in out and "reviewer wrote this" in out

    assert xp.main(["story", "story-001"]) == 0
    out = capsys.readouterr().out
    assert "nothing missing" in out and "xp.py story land story-001" in out
    assert not (sdir / "review-2.md").exists()


def test_question_stops_until_the_line_is_answered(repo, monkeypatch, capsys):
    monkeypatch.setenv("FAKE_QUESTION", "QUESTION: which store?")
    assert xp.main(["story", "story-001"]) == 3
    out = capsys.readouterr().out
    assert "QUESTION: which store?" in out and "answer it in the card" in out
    sdir = story(repo, "story-001")
    assert not (sdir / "handback.md").exists()
    assert xp.main(["story", "story-001"]) == 3

    plan = repo / "plan.md"
    plan.write_text(plan.read_text().replace("Context: c.", "Context: c. Store: sqlite."))
    review = sdir / "plan-review.md"
    review.write_text(review.read_text().replace("QUESTION: which store?", ""))
    assert xp.main(["story", "story-001"]) == 0
    assert (sdir / "review-1.md").is_file()
    log = (repo / "logs" / "story-001-plan-reviewer.log").read_text()
    assert log.count("===== story-001-plan-reviewer") == 1


def test_dirty_lead_tree_refuses(repo, capsys):
    (repo.parent / "repo" / ".xp" / "config.yml").write_text("roles:\n")
    with pytest.raises(SystemExit) as exc:
        xp.main(["story", "story-001"])
    assert exc.value.code == 2 and "git status" in capsys.readouterr().err
    assert not (repo / "worktrees").exists()


def test_story_without_sprint_branch_refuses(repo, capsys):
    (repo / "sprint_branch").unlink()
    with pytest.raises(SystemExit):
        xp.main(["story", "story-001"])
    assert "xp.py sprint open" in capsys.readouterr().err


def test_dry_run_names_stages_and_touches_nothing(repo, capsys):
    assert xp.main(["story", "story-001", "--dry-run"]) == 0
    expected = "would run worktree, planner, plan-reviewer, executor, reviewer"
    assert expected in capsys.readouterr().out
    assert not (repo / "worktrees").exists() and "[planned]" in (repo / "plan.md").read_text()


def test_free_mints_its_card_and_branches_from_trunk(repo):
    assert xp.main(["free", "fix-typo"]) == 0
    plan = (repo / "plan.md").read_text()
    assert plan.endswith("## Free\n\n#### free-fix-typo — fix-typo   [in-progress]\n")
    wt = repo / "worktrees" / "free-fix-typo"
    assert git("branch", "--show-current", cwd=wt).stdout.strip() == "free-fix-typo"
    assert git("log", "--format=%s", "main..HEAD", cwd=wt).stdout.split() == ["feat"]
    assert (story(repo, "free-fix-typo") / "review-1.md").is_file()
    assert xp.main(["free", "free-fix-typo"]) == 0
    assert (repo / "plan.md").read_text().count("free-fix-typo") == 1
