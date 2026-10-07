import os
import subprocess
import sys

import pytest
import xp

FAKE = """\
import json, os, re, subprocess, sys
prompt = sys.stdin.read()
paths = dict(re.findall(r"^- ([A-Z_]+): (.+)$", prompt, re.M))
role = re.search(r"^===== Your charter: (\\S+) =====$", prompt, re.M)[1]
data = os.environ["XP_DATA"]
with open(os.path.join(data, "roles.txt"), "a") as out:
    out.write(role + "\\n")
with open(os.path.join(data, f"{role}.prompt"), "w") as out:
    out.write(prompt)
key = {"planner": "PLAN_PATH", "executor": "HANDBACK_PATH"}.get(role, "FINDINGS_PATH")
extra = os.environ.get("FAKE_QUESTION", "") if role == "plan-reviewer" else ""
with open(paths[key], "w") as out:
    out.write(f"{role} wrote this\\n{extra}\\n")
if role == "plan-reviewer":  # it edits the card and plan in place, after its findings
    with open(paths["PLAN_PATH"], "a") as out:
        out.write("corrected\\n")
    if files := os.environ.get("FAKE_FILES"):
        card = os.path.join(data, "plan.md")
        text = open(card).read().replace("Files: a.py, b.py", files)
        open(card, "w").write(text)
if role == "executor" and not os.environ.get("FAKE_NO_COMMIT"):
    with open("feature.txt", "a") as out:
        out.write("x\\n")
    subprocess.run(["git", "add", "-A"], check=True)
    subprocess.run(["git", "commit", "-qm", "feat"], check=True)
if role == "executor" and os.environ.get("FAKE_EXEC_PLAN"):  # a deviations note
    with open(os.path.join(os.path.dirname(paths[key]), "plan.md"), "a") as out:
        out.write("deviation\\n")
if role == "executor" and os.environ.get("FAKE_EXIT"):
    sys.exit(1)
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
        "card.md",
        "handback.md",
        "review-1.md",
        "setup.ok",
    ]
    assert not (repo / "logs" / "story-002-planner.log").exists()


def test_full_walk_then_rerun_is_a_noop(repo, capsys):
    assert xp.main(["story", "story-001"]) == 0
    sdir = story(repo, "story-001")
    names = {"card.md", "plan.md", "plan-review.md", "handback.md", "review-1.md", "setup.ok"}
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


def test_free_mints_its_card_then_stops_for_the_lead(repo, capsys):
    assert xp.main(["free", "fix-typo"]) == 0
    plan = (repo / "plan.md").read_text()
    assert plan.endswith("## Free\n\n#### free-fix-typo — fix-typo   [planned]\n")
    assert "write Context, AC, Files and Acceptance" in capsys.readouterr().out
    assert not (repo / "worktrees" / "free-fix-typo").exists()
    assert xp.main(["free", "free-fix-typo"]) == 0
    assert (repo / "plan.md").read_text().count("free-fix-typo") == 1
    wt = repo / "worktrees" / "free-fix-typo"
    assert git("branch", "--show-current", cwd=wt).stdout.strip() == "free-fix-typo"
    assert git("log", "--format=%s", "main..HEAD", cwd=wt).stdout.split() == ["feat"]
    assert (story(repo, "free-fix-typo") / "review-1.md").is_file()


def roles(data):
    path = data / "roles.txt"
    roles_run = path.read_text().split() if path.exists() else []
    path.unlink(missing_ok=True)
    return roles_run


def test_a_lead_commit_after_review_reruns_only_the_reviewer(repo):
    assert xp.main(["story", "story-001"]) == 0
    assert roles(repo) == ["planner", "plan-reviewer", "executor", "reviewer"]
    sdir, wt = story(repo, "story-001"), repo / "worktrees" / "story-001"
    review = sdir / "review-1.md"
    head = git("rev-parse", "HEAD", cwd=wt).stdout.strip()
    assert review.read_text().endswith(f"reviewed: {head}\n")
    (wt / "lead.txt").write_text("lead\n")
    git("add", "-A", cwd=wt)
    git("commit", "-qm", "lead fix", cwd=wt)
    # The lead annotates the review after committing: a newer file covers nothing new.
    review.write_text(review.read_text() + "lead: fixed it\n")
    os.utime(review, (4_000_000_000, 4_000_000_000))
    assert xp.main(["story", "story-001"]) == 0
    assert roles(repo) == ["reviewer"] and (sdir / "review-2.md").is_file()


def test_a_handback_without_commits_reruns_the_executor(repo, monkeypatch, capsys):
    assert xp.main(["story", "story-002"]) == 0
    monkeypatch.setenv("GIT_COMMITTER_DATE", "@2000000000 +0000")  # not the reviewed commit
    roles(repo)
    git("reset", "-q", "--hard", "sprint-001", cwd=repo / "worktrees" / "story-002")
    capsys.readouterr()
    assert xp.main(["story", "story-002", "--dry-run"]) == 0
    assert "would run executor, reviewer" in capsys.readouterr().out
    assert xp.main(["story", "story-002"]) == 0
    assert roles(repo) == ["executor", "reviewer"]


def test_the_reviewer_sees_the_card_as_spawned_and_as_it_is_now(repo):
    assert xp.main(["story", "story-002"]) == 0
    spawned = (story(repo, "story-002") / "card.md").read_text()
    assert spawned.startswith("#### story-002 — One file   [in-progress]\nFiles: a.py")
    prompt = (repo / "reviewer.prompt").read_text()
    assert "## Card changes since spawn\n(none)" in prompt
    # A map and the command, not the hunks: the reviewer pulls the diff per file itself.
    assert "### Files\n" in prompt and " feature.txt " in prompt and "`git diff " in prompt
    assert "\n+" not in prompt.split("### Files")[1].split("## Handback")[0]
    plan = repo / "plan.md"
    plan.write_text(plan.read_text().replace("Files: a.py\n", "Files: a.py\nAC: less.\n"))
    assert xp.main(["story", "review", "story-002"]) == 0
    prompt = (repo / "reviewer.prompt").read_text()
    assert "## Card changes since spawn\n--- card as spawned\n+++ card now\n" in prompt
    assert "\n+AC: less.\n" in prompt
    assert xp.main(["story", "story-002"]) == 0
    assert (story(repo, "story-002") / "card.md").read_text() == spawned


def test_a_deleted_plan_replans_and_rereviews_the_plan(repo):
    assert xp.main(["story", "story-001"]) == 0
    roles(repo)
    (story(repo, "story-001") / "plan.md").unlink()
    assert xp.main(["story", "story-001"]) == 0
    assert roles(repo) == ["planner", "plan-reviewer"]


def test_an_executor_edit_to_the_plan_does_not_rereview_it(repo, monkeypatch):
    monkeypatch.setenv("FAKE_EXEC_PLAN", "1")
    assert xp.main(["story", "story-001"]) == 0
    assert roles(repo) == ["planner", "plan-reviewer", "executor", "reviewer"]


@pytest.mark.parametrize("line", ["- QUESTION: which store?", "**QUESTION:** which store?"])
def test_a_decorated_question_stops_the_story(repo, monkeypatch, capsys, line):
    monkeypatch.setenv("FAKE_QUESTION", line)
    assert xp.main(["story", "story-001"]) == 3
    assert "which store?" in capsys.readouterr().out
    assert not (story(repo, "story-001") / "handback.md").exists()


def test_story_review_dry_run_launches_nothing(repo, capsys):
    assert xp.main(["story", "story-002"]) == 0
    roles(repo)
    capsys.readouterr()
    assert xp.main(["story", "review", "story-002", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "would run the reviewer over " in out and "..HEAD" not in out
    assert roles(repo) == [] and not (story(repo, "story-002") / "review-2.md").exists()


@pytest.mark.parametrize(
    ("env", "said"), [("FAKE_NO_COMMIT", "committed nothing"), ("FAKE_EXIT", "exited 1")]
)
def test_a_failed_executor_names_its_log_and_reruns(repo, monkeypatch, capsys, env, said):
    monkeypatch.setenv(env, "1")
    with pytest.raises(SystemExit) as exc:
        xp.main(["story", "story-002"])
    err = capsys.readouterr().err
    assert exc.value.code == 1 and said in err
    assert str(repo / "logs" / "story-002-executor.log") in err
    assert not (story(repo, "story-002") / "handback.md").exists()


def test_each_stage_reads_the_card_as_the_last_stage_left_it(repo, monkeypatch):
    monkeypatch.setenv("FAKE_FILES", "Files: a.py, b.py, c.py")
    assert xp.main(["story", "story-001"]) == 0
    assert "Files: a.py, b.py, c.py" in (repo / "executor.prompt").read_text()
